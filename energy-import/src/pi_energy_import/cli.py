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


def testdata_target(ref_id: str, content: str) -> dict:
    return {"refId": ref_id, "scenarioId": "csv_content", "csvContent": content}


def panel(panel_id: int, title: str, csv_content: str, y: int, unit: str, fill_opacity: int = 0, bar_width_factor: float = 0.6) -> dict:
    return {
        "id": panel_id, "type": "timeseries", "title": title,
        "datasource": {"type": "grafana-testdata-datasource", "uid": "energy-static"},
        "gridPos": {"h": 10, "w": 24, "x": 0, "y": y},
        "fieldConfig": {"defaults": {"unit": unit, "custom": {"drawStyle": "bars", "barWidthFactor": bar_width_factor, "lineWidth": 1, "fillOpacity": fill_opacity, "showPoints": "never"}}, "overrides": []},
        "options": {"legend": {"displayMode": "table", "placement": "bottom", "showLegend": True}, "tooltip": {"mode": "multi"}},
        "transformations": [{"id": "convertFieldType", "options": {"fields": {}, "conversions": [{"targetField": "Time", "destinationType": "time", "dateFormat": "YYYY-MM-DD"}]} }],
        "targets": [testdata_target("A", csv_content)],
    }


def series_csv(rows: list[dict[str, str]], time_field: str, status_field: str) -> str:
    names = {"表示実績": "actual", "集計途中": "in_progress", "予測": "forecast"}
    points: dict[str, dict[str, str]] = {}
    for row in rows:
        point = points.setdefault(row[time_field], {})
        point[names.get(row[status_field], row[status_field])] = row["usage"]
    columns = ["Time", "actual", "in_progress", "forecast"]
    return ",".join(columns) + "\n" + "\n".join(
        ",".join([when] + [points[when].get(column, "") for column in columns[1:]])
        for when in sorted(points)
    )


def monthly_category_csv(rows: list[dict[str, str]], date_field: str) -> str:
    names = {"表示実績": "actual", "集計途中": "in_progress", "予測": "forecast"}
    points: dict[str, dict[str, str]] = {}
    for row in rows:
        point = points.setdefault(row[date_field][:7], {})
        point[names.get(row["status"], row["status"])] = row["usage"]
    columns = ["Period", "actual", "in_progress", "forecast"]
    return ",".join(columns) + "\n" + "\n".join(
        ",".join([period] + [points[period].get(column, "") for column in columns[1:]]) for period in sorted(points)
    )


def selected_csv(rows: list[dict[str, str]], time_field: str, fields: list[str]) -> str:
    return "Time," + ",".join(fields) + "\n" + "\n".join(
        ",".join([row[time_field]] + [row[field] for field in fields]) for row in rows
    )


def water_panel(panel_id: int, title: str, content: str, y: int, unit: str, names: dict[str, str], colors: dict[str, str], stacking: str = "none", show_value: str = "auto") -> dict:
    return {"id": panel_id, "type": "barchart", "title": title,
        "datasource": {"type": "grafana-testdata-datasource", "uid": "energy-static"},
        "gridPos": {"h": 10, "w": 24, "x": 0, "y": y},
        "fieldConfig": {"defaults": {"unit": unit}, "overrides": [{"matcher": {"id": "byName", "options": field}, "properties": [{"id": "displayName", "value": label}, {"id": "color", "value": {"mode": "fixed", "fixedColor": colors[field]}}]} for field, label in names.items()]},
        "options": {"orientation": "auto", "showValue": show_value, "stacking": stacking, "xField": "Period", "legend": {"displayMode": "table", "placement": "bottom", "showLegend": True}, "tooltip": {"mode": "multi"}},
        "targets": [testdata_target("A", content)]}


def monthly_panel(panel_id: int, title: str, content: str, y: int, unit: str) -> dict:
    return {"id": panel_id, "type": "barchart", "title": title,
        "datasource": {"type": "grafana-testdata-datasource", "uid": "energy-static"},
        "gridPos": {"h": 10, "w": 24, "x": 0, "y": y},
        "fieldConfig": {"defaults": {"unit": unit}, "overrides": []},
        "options": {"orientation": "auto", "showValue": "never", "stacking": "none", "xField": "Period", "legend": {"displayMode": "table", "placement": "bottom", "showLegend": True}, "tooltip": {"mode": "multi"}},
        "targets": [testdata_target("A", content)]}


def dashboard(rows: dict[str, list[dict[str, str]]], water: list[dict[str, str]], destination: Path) -> None:
    daily = series_csv(rows["日別使用量"], "date", "status")
    monthly_electric = monthly_category_csv([r for r in rows["月別使用量"] if r["kind"] == "電気"], "period_end")
    monthly_gas = monthly_category_csv([r for r in rows["月別使用量"] if r["kind"] == "ガス"], "display_month")
    electricity_charge = selected_csv([r for r in rows["請求明細"] if r["kind"] == "電気"], "billing_month", ["charge_yen"]).replace("charge_yen", "Charge", 1)
    gas_charge = selected_csv([r for r in rows["請求明細"] if r["kind"] == "ガス"], "billing_month", ["charge_yen"]).replace("charge_yen", "Charge", 1)
    water_usage = selected_csv(water, "billing_months", ["water_m3"]).replace("Time,", "Period,", 1)
    water_cost = selected_csv(water, "billing_months", ["water_fee_yen", "sewer_fee_yen"]).replace("Time,", "Period,", 1)
    body = {
        "annotations": {"list": []}, "editable": False,
        "description": "Private electricity and gas history imported manually from the provider portal.",
        "panels": [
            {"id": 1, "type": "text", "title": "About this dashboard", "gridPos": {"h": 5, "w": 24, "x": 0, "y": 0}, "options": {"mode": "markdown", "content": "### Electricity & gas usage\n\n- Updated manually from the provider portal; this is not live telemetry.\n- **Actual**, **in progress**, and **forecast** values must not be added together.\n- Electricity uses each record's period end date. Gas uses the provider display month on the first day of that month."}},
            panel(2, "Daily electricity usage", daily, 5, "kWh"),
            monthly_panel(3, "Monthly electricity usage", monthly_electric, 15, "kWh"),
            monthly_panel(4, "Monthly gas usage", monthly_gas, 25, "m3"),
            panel(7, "Electricity charges", electricity_charge, 35, "prefix:￥", 80, 0.5),
            panel(8, "Gas charges", gas_charge, 45, "prefix:￥", 80, 0.5),
            water_panel(5, "Water and sewer usage", water_usage, 55, "m3", {"water_m3": "Total usage"}, {"water_m3": "#1F78C1"}),
            water_panel(6, "Water and sewer charges", water_cost, 65, "prefix:￥", {"water_fee_yen": "Water", "sewer_fee_yen": "Sewer"}, {"water_fee_yen": "#1F78C1", "sewer_fee_yen": "#6ED0E0"}, "normal", "never"),
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
