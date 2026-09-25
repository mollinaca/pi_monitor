from __future__ import annotations

from pathlib import Path

from prometheus_client.parser import text_string_to_metric_families

from pi_ap_web_probe.cli import Credentials, Settings, Target, count_client_records, number, parse_wap_payload, radio_entries, write_metrics


def test_number_accepts_plain_numeric_values_only() -> None:
    assert number(12) == 12
    assert number(" 2.5 ") == 2.5
    assert number("54 Mbps") is None
    assert number(True) is None


def test_parse_wap_payload_accepts_only_numeric_division_expressions() -> None:
    assert parse_wap_payload('{"data_rate":650/10,"channel":44,}') == {"data_rate": 65.0, "channel": 44}
    assert parse_wap_payload('{"status":"ok\t",}') == {"status": "ok\t"}
    assert parse_wap_payload("{status:'ok',}") == {"status": "ok"}


def test_radio_entries_and_client_count_avoid_identifier_export() -> None:
    dashboard = {"wireless": {"wlan0": {"channel": 1}, "wlan1": {"channel": 44}}}
    associations = {"clients": [{"mac": "00:11:22:33:44:55"}, {"mac": "66:77:88:99:aa:bb"}]}
    assert radio_entries(dashboard) == [("wlan0", {"channel": 1}), ("wlan1", {"channel": 44})]
    assert count_client_records(associations) == 2


def test_write_metrics_records_failure_without_client_identifiers(tmp_path: Path, monkeypatch) -> None:
    settings = Settings(
        credentials_file=tmp_path / "credentials.toml",
        metrics_directory=tmp_path,
        metrics_filename="ap-web.prom",
        targets=(Target("ap1", "192.168.100.246", False, 45),),
    )

    def fail(*_args: object) -> tuple[object, object, float]:
        raise RuntimeError("unavailable")

    monkeypatch.setattr("pi_ap_web_probe.cli.collect_target", fail)
    output = write_metrics(settings, Credentials("user", "password"))
    values = {
        sample.name: sample.value
        for family in text_string_to_metric_families(output.read_text(encoding="utf-8"))
        for sample in family.samples
    }
    assert values["home_ap_web_probe_success"] == 0
    assert "00:11:22:33:44:55" not in output.read_text(encoding="utf-8")
