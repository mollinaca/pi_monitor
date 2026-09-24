from __future__ import annotations

from pathlib import Path

from prometheus_client.parser import text_string_to_metric_families

from pi_ssd_smart_probe.cli import Settings, attribute_raw_values, write_metrics


def payload() -> dict:
    return {
        "smart_status": {"passed": True},
        "temperature": {"current": 54},
        "power_on_time": {"hours": 15079},
        "power_cycle_count": 1081,
        "ata_smart_error_log": {"summary": {"count": 0}},
        "ata_smart_data": {"self_test": {"status": {"passed": True}}},
        "ata_smart_attributes": {
            "table": [
                {"id": 5, "raw": {"value": 0}},
                {"id": 232, "raw": {"value": 100}},
                {"id": 241, "raw": {"value": 25651}},
            ]
        },
    }


def samples(path: Path) -> dict[str, float]:
    families = text_string_to_metric_families(path.read_text(encoding="utf-8"))
    result: dict[str, float] = {}
    for family in families:
        for sample in family.samples:
            result[sample.name] = sample.value
    return result


def test_attribute_raw_values_extracts_only_integer_values() -> None:
    assert attribute_raw_values(payload()) == {5: 0, 232: 100, 241: 25651}


def test_write_metrics_includes_health_and_known_attributes(tmp_path: Path) -> None:
    settings = Settings(
        device="/dev/sda",
        device_type="sat",
        metrics_directory=tmp_path,
        metrics_filename="ssd-smart.prom",
    )

    output = write_metrics(settings, command_exit_status=0, payload=payload())
    values = samples(output)

    assert values["home_ssd_smart_probe_success"] == 1
    assert values["home_ssd_smart_overall_passed"] == 1
    assert values["home_ssd_smart_temperature_celsius"] == 54
    assert values["home_ssd_smart_available_reserved_space_percent"] == 100
    assert values["home_ssd_smart_total_lbas_written_raw"] == 25651


def test_write_metrics_records_probe_failure(tmp_path: Path) -> None:
    settings = Settings(
        device="/dev/sda",
        device_type="sat",
        metrics_directory=tmp_path,
        metrics_filename="ssd-smart.prom",
    )

    output = write_metrics(settings, command_exit_status=2, payload=None)
    values = samples(output)

    assert values["home_ssd_smart_probe_success"] == 0
    assert values["home_ssd_smart_overall_passed"] == 0
    assert values["home_ssd_smart_command_exit_status"] == 2
