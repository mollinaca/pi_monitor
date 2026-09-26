from __future__ import annotations

import argparse
import csv
import json
import os
import time
from datetime import date, datetime
from pathlib import Path

from openpyxl import load_workbook
from prometheus_client import CollectorRegistry, Gauge, write_to_textfile


DATASETS = {
    "月別使用量": ("monthly-usage.csv", ["kind", "display_month", "period_start", "period_end", "usage", "unit", "status"]),
    "請求明細": ("billing.csv", ["kind", "billing_month", "period_start", "period_end", "usage", "unit", "charge_yen"]),
    "日別使用量": ("daily-electricity.csv", ["kind", "date", "usage", "unit", "status"]),
}

WATER_COLUMNS = ["display_month", "meter_reading_date", "billing_months", "period_start", "period_end", "water_m3", "sewer_m3", "previous_water_m3", "prior_year_water_m3", "water_fee_yen", "sewer_fee_yen", "total_fee_yen"]


def iso(value: object) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def rows_for_sheet(sheet, columns: list[str]) -> list[dict[str, str]]:
    header_row = None
    positions: dict[str, int] = {}
    header_index = 0
    for header_index, row in enumerate(sheet.iter_rows(values_only=True), start=1):
        cells = [str(value).strip() if value is not None else "" for value in row]
        if cells and cells[0] == "種別":
            header_row = row
            positions = {name: cells.index(name) for name in cells if name in {"種別", "表示月", "請求月", "使用開始日", "使用終了日", "使用量", "単位", "区分", "利用料金（税込円）", "日付"}}
            break
    if header_row is None:
        raise ValueError(f"{sheet.title}: header row not found")

    source = {"kind": "種別", "display_month": "表示月", "billing_month": "請求月", "period_start": "使用開始日", "period_end": "使用終了日", "usage": "使用量", "unit": "単位", "status": "区分", "charge_yen": "利用料金（税込円）", "date": "日付"}
    output: list[dict[str, str]] = []
    for row in sheet.iter_rows(min_row=header_index + 1, values_only=True):
        if not row or row[0] is None:
            continue
        item: dict[str, str] = {}
        for field in columns:
            japanese = source[field]
            if japanese not in positions:
                raise ValueError(f"{sheet.title}: column {japanese} not found")
            value = row[positions[japanese]]
            item[field] = iso(value) if value is not None else ""
        output.append(item)
    if not output:
        raise ValueError(f"{sheet.title}: no data rows")
    return output


def write_csv(destination: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(destination)


def water_rows(source: Path) -> list[dict[str, str]]:
    names = {"表示月": "display_month", "検針日": "meter_reading_date", "使用期間": "period", "納入年月分": "billing_months", "水道使用量_㎥": "water_m3", "下水道使用量_㎥": "sewer_m3", "前回水道使用量_㎥": "previous_water_m3", "前年同期水道使用量_㎥": "prior_year_water_m3", "水道料金_円": "water_fee_yen", "下水道使用料_円": "sewer_fee_yen", "料金合計_円": "total_fee_yen"}
    with source.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or any(column not in reader.fieldnames for column in names):
            raise ValueError("water CSV has unexpected columns")
        result: list[dict[str, str]] = []
        for raw in reader:
            start, separator, end = raw["使用期間"].partition(" ～ ")
            if not separator:
                raise ValueError(f"water CSV has invalid period: {raw['使用期間']}")
            row = {field: raw[japanese].strip() for japanese, field in names.items() if field != "period"}
            row["period_start"], row["period_end"] = start, end
            result.append(row)
    if not result:
        raise ValueError("water CSV has no data rows")
    return result


def build_daily_electricity_panel(rows: list[dict[str, str]]) -> dict:
    status_names = {"表示実績": "actual", "集計途中": "in_progress", "予測": "forecast"}
    points: dict[str, dict[str, str]] = {}
    for row in rows:
        points.setdefault(row["date"], {})[status_names[row["status"]]] = row["usage"]
    content = "Time,actual,in_progress,forecast\n" + "\n".join(
        ",".join([when, points[when].get("actual", ""), points[when].get("in_progress", ""), points[when].get("forecast", "")])
        for when in sorted(points)
    )
    return {"id": 2, "type": "timeseries", "title": "Daily electricity usage", "datasource": {"type": "grafana-testdata-datasource", "uid": "energy-static"}, "gridPos": {"h": 10, "w": 24, "x": 0, "y": 5}, "fieldConfig": {"defaults": {"unit": "kWh", "custom": {"drawStyle": "bars", "barWidthFactor": 0.6, "lineWidth": 1, "fillOpacity": 0, "showPoints": "never"}}, "overrides": []}, "options": {"legend": {"displayMode": "table", "placement": "bottom", "showLegend": True}, "tooltip": {"mode": "multi"}}, "transformations": [{"id": "convertFieldType", "options": {"fields": {}, "conversions": [{"targetField": "Time", "destinationType": "time", "dateFormat": "YYYY-MM-DD"}]}}], "targets": [{"refId": "A", "scenarioId": "csv_content", "csvContent": content}]}


def build_monthly_electricity_panel(rows: list[dict[str, str]]) -> dict:
    """Build electricity alone: every imported provider display month remains selectable by time range."""
    status_names = {"表示実績": "actual", "集計途中": "in_progress", "予測": "forecast"}
    points: dict[str, dict[str, str]] = {}
    for row in rows:
        if row["kind"] == "電気":
            points.setdefault(row["display_month"], {})[status_names[row["status"]]] = row["usage"]
    content = "Time,actual,in_progress,forecast\n" + "\n".join(
        ",".join([when, points[when].get("actual", ""), points[when].get("in_progress", ""), points[when].get("forecast", "")])
        for when in sorted(points)
    )
    return {"id": 3, "type": "timeseries", "title": "Monthly electricity usage", "datasource": {"type": "grafana-testdata-datasource", "uid": "energy-static"}, "gridPos": {"h": 10, "w": 24, "x": 0, "y": 15}, "fieldConfig": {"defaults": {"unit": "kWh", "custom": {"drawStyle": "bars", "barWidthFactor": 0.5, "lineWidth": 1, "fillOpacity": 80, "showPoints": "never"}}, "overrides": []}, "options": {"legend": {"displayMode": "table", "placement": "bottom", "showLegend": True}, "tooltip": {"mode": "multi"}}, "transformations": [{"id": "convertFieldType", "options": {"fields": {}, "conversions": [{"targetField": "Time", "destinationType": "time", "dateFormat": "YYYY-MM-DD"}]}}], "targets": [{"refId": "A", "scenarioId": "csv_content", "csvContent": content}]}


def build_monthly_gas_panel(rows: list[dict[str, str]]) -> dict:
    """Build gas alone so a gas-specific display change cannot affect electricity."""
    status_names = {"表示実績": "actual", "集計途中": "in_progress", "予測": "forecast"}
    points: dict[str, dict[str, str]] = {}
    for row in rows:
        if row["kind"] == "ガス":
            points.setdefault(row["display_month"], {})[status_names[row["status"]]] = row["usage"]
    content = "Time,actual,in_progress,forecast\n" + "\n".join(
        ",".join([when, points[when].get("actual", ""), points[when].get("in_progress", ""), points[when].get("forecast", "")])
        for when in sorted(points)
    )
    return {"id": 4, "type": "timeseries", "title": "Monthly gas usage", "datasource": {"type": "grafana-testdata-datasource", "uid": "energy-static"}, "gridPos": {"h": 10, "w": 24, "x": 0, "y": 25}, "fieldConfig": {"defaults": {"unit": "m3", "custom": {"drawStyle": "bars", "barWidthFactor": 0.5, "lineWidth": 1, "fillOpacity": 80, "showPoints": "never"}}, "overrides": []}, "options": {"legend": {"displayMode": "table", "placement": "bottom", "showLegend": True}, "tooltip": {"mode": "multi"}}, "transformations": [{"id": "convertFieldType", "options": {"fields": {}, "conversions": [{"targetField": "Time", "destinationType": "time", "dateFormat": "YYYY-MM-DD"}]}}], "targets": [{"refId": "A", "scenarioId": "csv_content", "csvContent": content}]}


def build_electricity_charge_panel(rows: list[dict[str, str]]) -> dict:
    content = "Time,Charge\n" + "\n".join(f"{row['billing_month']},{row['charge_yen']}" for row in rows if row["kind"] == "電気")
    return {"id": 7, "type": "timeseries", "title": "Electricity charges", "datasource": {"type": "grafana-testdata-datasource", "uid": "energy-static"}, "gridPos": {"h": 10, "w": 24, "x": 0, "y": 35}, "fieldConfig": {"defaults": {"unit": "prefix:￥", "custom": {"drawStyle": "bars", "barWidthFactor": 0.5, "lineWidth": 1, "fillOpacity": 80, "showPoints": "never"}}, "overrides": []}, "options": {"legend": {"displayMode": "table", "placement": "bottom", "showLegend": True}, "tooltip": {"mode": "multi"}}, "transformations": [{"id": "convertFieldType", "options": {"fields": {}, "conversions": [{"targetField": "Time", "destinationType": "time", "dateFormat": "YYYY-MM-DD"}]}}], "targets": [{"refId": "A", "scenarioId": "csv_content", "csvContent": content}]}


def build_gas_charge_panel(rows: list[dict[str, str]]) -> dict:
    content = "Time,Charge\n" + "\n".join(f"{row['billing_month']},{row['charge_yen']}" for row in rows if row["kind"] == "ガス")
    return {"id": 8, "type": "timeseries", "title": "Gas charges", "datasource": {"type": "grafana-testdata-datasource", "uid": "energy-static"}, "gridPos": {"h": 10, "w": 24, "x": 0, "y": 45}, "fieldConfig": {"defaults": {"unit": "prefix:￥", "custom": {"drawStyle": "bars", "barWidthFactor": 0.5, "lineWidth": 1, "fillOpacity": 80, "showPoints": "never"}}, "overrides": []}, "options": {"legend": {"displayMode": "table", "placement": "bottom", "showLegend": True}, "tooltip": {"mode": "multi"}}, "transformations": [{"id": "convertFieldType", "options": {"fields": {}, "conversions": [{"targetField": "Time", "destinationType": "time", "dateFormat": "YYYY-MM-DD"}]}}], "targets": [{"refId": "A", "scenarioId": "csv_content", "csvContent": content}]}


def build_water_usage_panel(rows: list[dict[str, str]]) -> dict:
    content = "Period,water_m3\n" + "\n".join(f"{row['billing_months']},{row['water_m3']}" for row in rows)
    return {"id": 5, "type": "barchart", "title": "Water and sewer usage", "datasource": {"type": "grafana-testdata-datasource", "uid": "energy-static"}, "gridPos": {"h": 10, "w": 24, "x": 0, "y": 55}, "fieldConfig": {"defaults": {"unit": "m3"}, "overrides": [{"matcher": {"id": "byName", "options": "water_m3"}, "properties": [{"id": "displayName", "value": "Total usage"}, {"id": "color", "value": {"mode": "fixed", "fixedColor": "#1F78C1"}}]}]}, "options": {"orientation": "auto", "showValue": "auto", "stacking": "none", "xField": "Period", "legend": {"displayMode": "table", "placement": "bottom", "showLegend": True}, "tooltip": {"mode": "multi"}}, "targets": [{"refId": "A", "scenarioId": "csv_content", "csvContent": content}]}


def build_water_charge_panel(rows: list[dict[str, str]]) -> dict:
    content = "Period,water_fee_yen,sewer_fee_yen\n" + "\n".join(f"{row['billing_months']},{row['water_fee_yen']},{row['sewer_fee_yen']}" for row in rows)
    return {"id": 6, "type": "barchart", "title": "Water and sewer charges", "datasource": {"type": "grafana-testdata-datasource", "uid": "energy-static"}, "gridPos": {"h": 10, "w": 24, "x": 0, "y": 65}, "fieldConfig": {"defaults": {"unit": "prefix:￥"}, "overrides": [{"matcher": {"id": "byName", "options": "water_fee_yen"}, "properties": [{"id": "displayName", "value": "Water"}, {"id": "color", "value": {"mode": "fixed", "fixedColor": "#1F78C1"}}]}, {"matcher": {"id": "byName", "options": "sewer_fee_yen"}, "properties": [{"id": "displayName", "value": "Sewer"}, {"id": "color", "value": {"mode": "fixed", "fixedColor": "#6ED0E0"}}]}]}, "options": {"orientation": "auto", "showValue": "never", "stacking": "normal", "xField": "Period", "legend": {"displayMode": "table", "placement": "bottom", "showLegend": True}, "tooltip": {"mode": "multi"}}, "targets": [{"refId": "A", "scenarioId": "csv_content", "csvContent": content}]}


def dashboard(rows: dict[str, list[dict[str, str]]], water: list[dict[str, str]], destination: Path) -> None:
    body = {
        "annotations": {"list": []}, "editable": False,
        "description": "Private electricity and gas history imported manually from the provider portal.",
        "panels": [
            {"id": 1, "type": "text", "title": "About this dashboard", "gridPos": {"h": 5, "w": 24, "x": 0, "y": 0}, "options": {"mode": "markdown", "content": "### Electricity & gas usage\n\n- Updated manually from the provider portal; this is not live telemetry.\n- **Actual**, **in progress**, and **forecast** values must not be added together.\n- Electricity uses each record's period end date. Gas uses the provider display month on the first day of that month."}},
            build_daily_electricity_panel(rows["日別使用量"]),
            build_monthly_electricity_panel(rows["月別使用量"]),
            build_monthly_gas_panel(rows["月別使用量"]),
            build_electricity_charge_panel(rows["請求明細"]),
            build_gas_charge_panel(rows["請求明細"]),
            build_water_usage_panel(water),
            build_water_charge_panel(water),
        ],
        "schemaVersion": 42, "tags": ["energy", "electricity", "gas"],
        "time": {"from": "now-1y", "to": "now"}, "timezone": "browser",
        "title": "Energy Usage", "uid": "energy-usage", "version": 1,
    }
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(destination)


def write_metrics(path: Path, counts: dict[str, int]) -> None:
    registry = CollectorRegistry()
    Gauge("home_energy_import_success", "1 when the latest energy workbook import succeeded", registry=registry).set(1)
    Gauge("home_energy_import_timestamp_seconds", "Unix timestamp of the latest energy workbook import", registry=registry).set(time.time())
    rows = Gauge("home_energy_import_rows", "Rows imported from the energy workbook", ["dataset"], registry=registry)
    for name, count in counts.items():
        rows.labels(dataset=name).set(count)
    write_to_textfile(str(path), registry)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("workbook", type=Path)
    parser.add_argument("--data-directory", type=Path, default=Path("data/energy"))
    parser.add_argument("--dashboard", type=Path, default=Path("services/grafana/dashboards/energy/energy-usage.json"))
    parser.add_argument("--metrics", type=Path, default=Path("data/node-exporter/textfile/energy-import.prom"))
    parser.add_argument("--water-csv", type=Path)
    args = parser.parse_args()
    workbook = load_workbook(args.workbook, data_only=True, read_only=True)
    imported: dict[str, list[dict[str, str]]] = {}
    args.data_directory.mkdir(parents=True, exist_ok=True)
    args.dashboard.parent.mkdir(parents=True, exist_ok=True)
    args.metrics.parent.mkdir(parents=True, exist_ok=True)
    for sheet_name, (filename, columns) in DATASETS.items():
        imported[sheet_name] = rows_for_sheet(workbook[sheet_name], columns)
        write_csv(args.data_directory / filename, columns, imported[sheet_name])
    water_destination = args.data_directory.parent / "water" / "water-usage.csv"
    water_destination.parent.mkdir(parents=True, exist_ok=True)
    if args.water_csv:
        water = water_rows(args.water_csv)
        write_csv(water_destination, WATER_COLUMNS, water)
    elif water_destination.exists():
        with water_destination.open(encoding="utf-8", newline="") as handle:
            water = list(csv.DictReader(handle))
    else:
        water = []
    dashboard(imported, water, args.dashboard)
    counts = {name: len(rows) for name, rows in imported.items()}
    counts["水道"] = len(water)
    write_metrics(args.metrics, counts)


if __name__ == "__main__":
    main()
