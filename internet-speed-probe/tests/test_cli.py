from __future__ import annotations

from pathlib import Path

from prometheus_client.parser import text_string_to_metric_families

from pi_internet_speed_probe.cli import Settings, parse_result, write_metrics


def settings(directory: Path) -> Settings:
    return Settings(
        speedtest_binary=Path("/usr/bin/speedtest"),
        interface="eth0",
        server_id=48463,
        server_name="IPA CyberLab 400G",
        server_location="Tokyo, Japan",
        timeout_seconds=120,
        metrics_directory=directory,
        metrics_filename="internet-speed.prom",
    )


def payload() -> dict:
    return {
        "type": "result",
        "ping": {"jitter": 0.2, "latency": 4.6},
        "download": {"bandwidth": 109703076, "bytes": 800789269},
        "upload": {"bandwidth": 35928086, "bytes": 162650910},
        "packetLoss": 0,
    }


def samples(path: Path) -> dict[str, float]:
    families = text_string_to_metric_families(path.read_text(encoding="utf-8"))
    return {sample.name: sample.value for family in families for sample in family.samples}


def test_parse_result_ignores_non_json_and_selects_result() -> None:
    output = "License acceptance recorded.\n{\"type\": \"log\"}\n" + str(payload()).replace("'", '"')
    assert parse_result(output) == payload()


def test_write_metrics_records_a_successful_test(tmp_path: Path) -> None:
    output = write_metrics(settings(tmp_path), command_exit_status=0, payload=payload(), duration_seconds=12.3)
    values = samples(output)
    assert values["home_internet_speedtest_probe_success"] == 1
    assert values["home_internet_speedtest_download_bytes_per_second"] == 109703076
    assert values["home_internet_speedtest_upload_bytes_per_second"] == 35928086
    assert values["home_internet_speedtest_ping_latency_milliseconds"] == 4.6


def test_write_metrics_records_a_failed_test_without_false_zero_speed(tmp_path: Path) -> None:
    output = write_metrics(settings(tmp_path), command_exit_status=1, payload=None, duration_seconds=3.2)
    values = samples(output)
    assert values["home_internet_speedtest_probe_success"] == 0
    assert values["home_internet_speedtest_command_exit_status"] == 1
    assert "home_internet_speedtest_download_bytes_per_second" not in values
