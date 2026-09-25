# AP Web probe

Read-only Cisco WAP150 web UI probe. It intentionally does not use SNMP and
does not submit configuration changes. The AP account must be Read Only.

Create the Pi-only credentials file before installation:

```toml
# /root/.config/pi_monitor/ap-web-probe.toml (mode 0600)
[auth]
username = "pi_monitor"
password = "..."
```

The current AP uses a self-signed certificate. This is explicitly represented
by `verify_tls = false` in `config/probe.toml`; restrict AP management access
to the Pi when practical.

The probe logs in through a headless browser, reads the WAP150 associations
page's already-evaluated `allData.clients`, logs out, and atomically writes
`ap-web.prom`. Aggregate metrics are public to the local monitoring stack.
The current client-inventory metric intentionally includes MAC addresses,
hostnames, SSIDs, AP, and band as Prometheus labels so that the private Grafana
dashboard can show the live topology. These values are runtime-only Pi data:
do not add a real device-name mapping file or any client identifier to Git.

Optional root-only device-name overrides live at
`/root/.config/pi_monitor/device-names.toml`; start from
`config/device-names.example.toml` and use mode `0600`.

Current exported metrics are AP-wide associated-client count, and the
associated-client count plus average UI-reported link data rate (Mbps) grouped
by the bounded `2_4ghz`, `5ghz`, or `unknown` band label. Per-client traffic
counters are deliberately not exported until their direction and reset
semantics have been verified.
