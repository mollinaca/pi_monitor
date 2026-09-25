from __future__ import annotations

import argparse
import json
import os
import re
import ssl
import sys
import time
import tomllib
from dataclasses import dataclass
from http.cookiejar import Cookie, CookieJar
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, HTTPSHandler, Request, build_opener

import json5
from prometheus_client import CollectorRegistry, Gauge, write_to_textfile
from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


@dataclass(frozen=True)
class Target:
    identifier: str
    address: str
    verify_tls: bool
    timeout_seconds: int

    @property
    def base_url(self) -> str:
        return f"https://{self.address}"


@dataclass(frozen=True)
class Settings:
    credentials_file: Path
    metrics_directory: Path
    metrics_filename: str
    targets: tuple[Target, ...]

    @property
    def metrics_path(self) -> Path:
        return self.metrics_directory / self.metrics_filename


@dataclass(frozen=True)
class Credentials:
    username: str
    password: str


def load_settings(path: Path) -> Settings:
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    probe = data.get("probe")
    targets = data.get("targets")
    if not isinstance(probe, dict) or not isinstance(targets, list) or not targets:
        raise ValueError("[probe] and at least one [[targets]] table are required")
    required = ("credentials_file", "metrics_directory", "metrics_filename")
    if any(not isinstance(probe.get(key), str) or not probe[key] for key in required):
        raise ValueError("probe configuration contains missing or invalid string values")
    filename = probe["metrics_filename"]
    if Path(filename).name != filename or not filename.endswith(".prom"):
        raise ValueError("metrics_filename must be a plain .prom filename")
    configured: list[Target] = []
    identifiers: set[str] = set()
    for target in targets:
        if not isinstance(target, dict):
            raise ValueError("each target must be a TOML table")
        identifier, address = target.get("id"), target.get("address")
        verify_tls, timeout = target.get("verify_tls"), target.get("timeout_seconds")
        if not isinstance(identifier, str) or not identifier or not re.fullmatch(r"[a-z0-9_-]+", identifier):
            raise ValueError("target id must contain only lowercase letters, digits, _ or -")
        if identifier in identifiers or not isinstance(address, str) or not address:
            raise ValueError("target ids and addresses must be non-empty and unique")
        if not isinstance(verify_tls, bool) or not isinstance(timeout, int) or timeout <= 0:
            raise ValueError("target verify_tls and timeout_seconds are required")
        identifiers.add(identifier)
        configured.append(Target(identifier, address, verify_tls, timeout))
    return Settings(Path(probe["credentials_file"]), Path(probe["metrics_directory"]), filename, tuple(configured))


def load_credentials(path: Path) -> Credentials:
    mode = path.stat().st_mode & 0o777
    if mode & 0o077:
        raise ValueError(f"credentials file must not be group/world readable: {path}")
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    auth = data.get("auth")
    if not isinstance(auth, dict):
        raise ValueError("[auth] table is required in credentials file")
    username, password = auth.get("username"), auth.get("password")
    if not isinstance(username, str) or not username or not isinstance(password, str) or not password:
        raise ValueError("credentials file must provide non-empty username and password")
    return Credentials(username, password)


def make_cookie(name: str, value: str, domain: str) -> Cookie:
    return Cookie(0, name, value, None, False, domain, False, False, "/", True, False, None, True, None, None, {})


_NUMERIC_DIVISION = re.compile(r"(?<![A-Za-z0-9_.])-?[0-9]+(?:\.[0-9]+)?\s*/\s*-?[0-9]+(?:\.[0-9]+)?(?![A-Za-z0-9_.])")
_TRAILING_COMMA = re.compile(r",\s*([}\]])")
_MEMBER_REFERENCE = re.compile(r"(:\s*)[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)+(?=\s*[,}\]])")


def parse_wap_payload(body: str) -> Any:
    """Parse the WAP150's JavaScript-compatible, but non-strict, JSON payload.

    The firmware returns values such as ``650/10`` for some data rates. Its
    browser UI evaluates these expressions. Only a pair of numeric literals
    separated by division is accepted here; arbitrary JavaScript is never run.
    """

    payload = body.split("<!--", 1)[0]

    def replace_division(match: re.Match[str]) -> str:
        left, right = match.group(0).split("/", 1)
        denominator = float(right)
        if denominator == 0:
            raise ValueError("AP payload contains division by zero")
        return str(float(left) / denominator)

    normalized = _NUMERIC_DIVISION.sub(replace_division, payload)
    # Dashboard responses also contain display-only JavaScript member
    # references. They are not measurements and are never evaluated.
    normalized = _MEMBER_REFERENCE.sub(r"\1null", normalized)
    # Some firmware strings contain literal control characters. JavaScript
    # accepts these in the UI payload, whereas strict JSON rejects them.
    return json5.loads(_TRAILING_COMMA.sub(r"\1", normalized))


class WapClient:
    def __init__(self, target: Target, credentials: Credentials) -> None:
        self.target = target
        self.credentials = credentials
        self.cookies = CookieJar()
        context = ssl.create_default_context() if target.verify_tls else ssl._create_unverified_context()
        self.opener = build_opener(HTTPCookieProcessor(self.cookies), HTTPSHandler(context=context))

    def request(self, path: str, data: dict[str, str] | None = None) -> str:
        payload = urlencode(data).encode() if data is not None else None
        request = Request(
            self.target.base_url + path,
            data=payload,
            headers={"User-Agent": "pi-monitor-ap-web-probe/0.1", "Content-Type": "application/x-www-form-urlencoded"},
        )
        with self.opener.open(request, timeout=self.target.timeout_seconds) as response:
            return response.read().decode("utf-8", errors="replace")

    def login(self) -> None:
        self.request("/")
        response = self.request(
            "/admin.cgi?action=logon",
            {
                "i_username": self.credentials.username,
                "i_password": __import__("base64").b64encode(self.credentials.password.encode()).decode(),
                "locale": "en",
                "login": "",
                "login_times": "1",
                "protocol": "https",
                "local_addr": self.target.address,
            },
        )
        result = re.search(r'lg_ret="([0-9]+)-([0-9]+)-lgEnd"', response)
        session = re.search(r'cookie_info="([^"-]+)-([^"-]+)-cookieEnd"', response)
        if result is None or result.group(1) == "0" or session is None:
            error = result.group(2) if result is not None else "unknown"
            raise RuntimeError(f"AP web login failed (status={error})")
        self.cookies.set_cookie(make_cookie(session.group(1), session.group(2), self.target.address))

    def get_json(self, action: str) -> Any:
        body = self.request(f"/admin.cgi?action={action}")
        try:
            return parse_wap_payload(body)
        except (ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"AP response for {action} could not be parsed: {exc}") from exc

    def logout(self) -> None:
        try:
            self.request("/admin.cgi?action=logout")
        except OSError:
            pass


class BrowserWapClient:
    """Use the AP's supported browser path for its JavaScript payload format."""

    def __init__(self, target: Target, credentials: Credentials) -> None:
        options = Options()
        options.binary_location = "/usr/bin/chromium"
        # The WAP150 starts long-polling from some pages. Waiting for the full
        # load event can therefore block Selenium before DOM inspection.
        options.page_load_strategy = "eager"
        for argument in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--ignore-certificate-errors"):
            options.add_argument(argument)
        self.target = target
        self.credentials = credentials
        self.driver = webdriver.Chrome(service=Service("/usr/bin/chromedriver"), options=options)
        self.wait = WebDriverWait(self.driver, target.timeout_seconds)

    def login(self) -> None:
        self.driver.get(self.target.base_url + "/")
        self.wait.until(EC.presence_of_element_located((By.ID, "login-name"))).send_keys(self.credentials.username)
        self.driver.find_element(By.ID, "i_password_1").send_keys(self.credentials.password)
        self.driver.execute_script("EncryptPassword()")
        self.wait.until(lambda driver: "/admin.cgi?action=main" in driver.current_url)

    def associated_clients(self) -> list[dict[str, Any]]:
        """Return the UI's already-evaluated client records.

        The WAP150 serves JavaScript expressions rather than JSON for this
        page.  Its own browser UI evaluates those expressions and publishes
        the resulting records as ``allData.clients``.  Reading that value
        avoids maintaining a partial JavaScript parser in the collector.
        """
        self.driver.get(self.target.base_url + "/admin.cgi?action=associations")
        data = self.wait.until(
            lambda driver: driver.execute_script(
                "return window.allData && Array.isArray(window.allData.clients) ? window.allData.clients : null"
            )
        )
        if not isinstance(data, list):
            raise RuntimeError("AP associations page did not provide a client list")
        return normalize_client_records(data)

    def close(self) -> None:
        try:
            # Do not navigate to logout: the AP can keep the current page's
            # long-poll request open. Send a bounded background request, then
            # always terminate the browser process.
            self.driver.execute_async_script(
                """
                const done = arguments[arguments.length - 1];
                const controller = new AbortController();
                const timer = setTimeout(() => { controller.abort(); done(); }, 1500);
                fetch('/admin.cgi?action=logout', {signal: controller.signal})
                  .catch(() => undefined)
                  .finally(() => { clearTimeout(timer); done(); });
                """
            )
        finally:
            self.driver.quit()


def number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        match = re.fullmatch(r"\s*(-?[0-9]+(?:\.[0-9]+)?)\s*", value)
        return float(match.group(1)) if match else None
    return None


def radio_entries(value: Any) -> list[tuple[str, dict[str, Any]]]:
    if not isinstance(value, dict):
        return []
    result: list[tuple[str, dict[str, Any]]] = []
    for name, details in value.items():
        if name in {"wlan0", "wlan1"} and isinstance(details, dict):
            result.append((name, details))
        result.extend(radio_entries(details))
    return result


def count_client_records(value: Any) -> int:
    if isinstance(value, list):
        return sum(count_client_records(item) for item in value)
    if not isinstance(value, dict):
        return 0
    own = 1 if isinstance(value.get("mac"), str) else 0
    return own + sum(count_client_records(item) for item in value.values())


_CLIENT_MAC = re.compile(r"^[0-9a-f]{2}(?::[0-9a-f]{2}){5}$", re.IGNORECASE)
_CLIENT_STRING_FIELDS = ("ip", "hostname", "ssid", "mode", "uptime", "snr", "channel")
_CLIENT_NUMBER_FIELDS = ("data_rate", "uplink", "downlink")


def normalize_client_records(records: list[Any]) -> list[dict[str, Any]]:
    """Keep only valid, documented association fields from the AP UI."""
    normalized: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        mac = record.get("mac")
        if not isinstance(mac, str) or _CLIENT_MAC.fullmatch(mac.strip()) is None:
            continue
        client: dict[str, Any] = {"mac": mac.strip().lower()}
        for field in _CLIENT_STRING_FIELDS:
            value = record.get(field)
            if isinstance(value, str):
                client[field] = value
        for field in _CLIENT_NUMBER_FIELDS:
            value = number(record.get(field))
            if value is not None:
                client[field] = value
        normalized.append(client)
    return normalized


def band_for_channel(channel: Any) -> str:
    """Map a Wi-Fi channel to a bounded Prometheus label value."""
    channel_number = number(channel)
    if channel_number is None or not channel_number.is_integer():
        return "unknown"
    if 1 <= channel_number <= 14:
        return "2_4ghz"
    if 32 <= channel_number <= 196:
        return "5ghz"
    return "unknown"


def band_aggregates(records: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """Aggregate association data without exporting client identifiers."""
    aggregates: dict[str, dict[str, float]] = {}
    for record in records:
        band = band_for_channel(record.get("channel"))
        values = aggregates.setdefault(band, {"clients": 0.0, "data_rate_total": 0.0, "data_rate_samples": 0.0})
        values["clients"] += 1
        data_rate = number(record.get("data_rate"))
        if data_rate is not None:
            values["data_rate_total"] += data_rate
            values["data_rate_samples"] += 1
    return aggregates


def collect_target(target: Target, credentials: Credentials) -> tuple[Any, Any, float]:
    started = time.monotonic()
    client = BrowserWapClient(target, credentials)
    try:
        client.login()
        # Client details intentionally remain in-process at this stage.  The
        # textfile collector exports only the aggregate count below.
        return {}, {"clients": client.associated_clients()}, time.monotonic() - started
    finally:
        client.close()


def write_metrics(settings: Settings, credentials: Credentials) -> Path:
    settings.metrics_directory.mkdir(parents=True, exist_ok=True)
    registry = CollectorRegistry()
    labels = ("ap", "address")
    success = Gauge("home_ap_web_probe_success", "1 if the AP read-only web probe succeeded", labels, registry=registry)
    attempt = Gauge("home_ap_web_probe_timestamp_seconds", "Unix timestamp of the latest AP web probe attempt", labels, registry=registry)
    duration = Gauge("home_ap_web_probe_duration_seconds", "Wall-clock duration of the latest AP web probe", labels, registry=registry)
    clients = Gauge("home_ap_web_associated_clients", "Associated clients reported by the AP", labels, registry=registry)
    band_labels = labels + ("band",)
    band_clients = Gauge(
        "home_ap_web_band_associated_clients",
        "Associated clients reported by the AP, grouped by Wi-Fi band",
        band_labels,
        registry=registry,
    )
    band_data_rate = Gauge(
        "home_ap_web_band_average_data_rate_mbps",
        "Average client link data rate reported by the AP UI, grouped by Wi-Fi band",
        band_labels,
        registry=registry,
    )
    for target in settings.targets:
        values = (target.identifier, target.address)
        attempt.labels(*values).set(time.time())
        try:
            dashboard, associations, elapsed = collect_target(target, credentials)
            success.labels(*values).set(1)
            duration.labels(*values).set(elapsed)
            clients.labels(*values).set(count_client_records(associations))
            for band, aggregate in band_aggregates(associations["clients"]).items():
                band_clients.labels(*values, band).set(aggregate["clients"])
                if aggregate["data_rate_samples"]:
                    band_data_rate.labels(*values, band).set(
                        aggregate["data_rate_total"] / aggregate["data_rate_samples"]
                    )
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError, WebDriverException) as exc:
            print(f"AP web probe failed for {target.identifier}: {exc}", file=sys.stderr)
            success.labels(*values).set(0)
    write_to_textfile(str(settings.metrics_path), registry)
    # The probe runs as root to protect the AP credential, while node_exporter
    # runs in an unprivileged container.  Prometheus textfiles contain only
    # aggregate metrics and must remain readable by that container.
    os.chmod(settings.metrics_path, 0o644)
    return settings.metrics_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect read-only AP web UI metrics")
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        settings = load_settings(args.config)
        credentials = load_credentials(settings.credentials_file)
        destination = write_metrics(settings, credentials)
    except (OSError, ValueError) as exc:
        print(f"AP web probe failed before writing metrics: {exc}", file=sys.stderr)
        return 1
    print(f"AP web probe metrics written to {destination}")
    return 0
