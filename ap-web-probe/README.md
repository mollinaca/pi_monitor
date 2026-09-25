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

The probe logs in, reads `get_dashboard_info` and `associations_info`, logs
out, and atomically writes `ap-web.prom`. It never exports MAC addresses, IP
addresses, hostnames, or SSIDs as Prometheus labels.
