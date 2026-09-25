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
`ap-web.prom`. It never exports MAC addresses, IP addresses, hostnames, or
SSIDs as Prometheus labels.

Current exported metrics are AP-wide associated-client count, and the
associated-client count plus average UI-reported link data rate (Mbps) grouped
by the bounded `2_4ghz`, `5ghz`, or `unknown` band label. Per-client traffic
counters are deliberately not exported until their direction and reset
semantics have been verified.
