from __future__ import annotations

from pathlib import Path

from prometheus_client.parser import text_string_to_metric_families

from pi_ssd_smart_probe.cli import Settings, attribute_raw_values, valid_smart_payload, write_metrics


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
    assert "home_ssd_smart_overall_passed" not in values
    assert values["home_ssd_smart_command_exit_status"] == 2


def test_unknown_health_is_not_reported_as_failed_health(tmp_path: Path) -> None:
    settings = Settings("/dev/sda", "sat", tmp_path, "ssd-smart.prom")
    output = write_metrics(settings, command_exit_status=0, payload={"temperature": {"current": 40}})
    values = samples(output)
    assert not valid_smart_payload({"temperature": {"current": 40}})
    assert values["home_ssd_smart_probe_success"] == 0
    assert "home_ssd_smart_overall_passed" not in values


def test_unhealthy_device_is_still_a_successful_read(tmp_path: Path) -> None:
    settings = Settings("/dev/sda", "sat", tmp_path, "ssd-smart.prom")
    output = write_metrics(settings, command_exit_status=8, payload={"smart_status": {"passed": False}})
    values = samples(output)
    assert valid_smart_payload({"smart_status": {"passed": False}})
    assert values["home_ssd_smart_probe_success"] == 1
    assert values["home_ssd_smart_overall_passed"] == 0


def test_main_distinguishes_invalid_read_from_unhealthy_device(tmp_path: Path, monkeypatch, capsys) -> None:
    from pi_ssd_smart_probe import cli

    settings = Settings("/dev/sda", "sat", tmp_path, "ssd-smart.prom")
    monkeypatch.setattr(cli, "load_settings", lambda _path: settings)
    monkeypatch.setattr(cli, "run_smartctl", lambda _settings: (0, {}, ""))
    assert cli.main(["--config", "unused"]) == 1
    assert "error=invalid_result" in capsys.readouterr().err
    monkeypatch.setattr(cli, "run_smartctl", lambda _settings: (8, {"smart_status": {"passed": False}}, ""))
    assert cli.main(["--config", "unused"]) == 0
