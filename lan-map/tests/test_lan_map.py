import json
import sqlite3
from pathlib import Path

from cli import AccessPoint, Settings, build_topology, parse_arp, parse_switch_ports, run


AP1 = AccessPoint("ap1", "AP-1F", "192.0.2.10", 2)
AP2 = AccessPoint("ap2", "AP-2F", "192.0.2.11", 5)


def settings(tmp_path: Path) -> Settings:
    return Settings(
        router_snapshot=tmp_path / "router.json",
        ap_snapshot_directory=tmp_path / "ap",
        device_names_file=tmp_path / "device-names.toml",
        pi_mac_file=tmp_path / "eth0-address",
        database=tmp_path / "private" / "history.db",
        metrics=tmp_path / "metrics" / "lan-map.prom",
        access_points=(AP1, AP2),
    )


def write_inputs(config: Settings, cycle_at: int) -> None:
    config.ap_snapshot_directory.mkdir()
    config.router_snapshot.write_text(json.dumps({
        "collected_at": cycle_at + 45,
        "responses": {
            "show status switching-hub macaddress": (
                "port 2:2\n  00:11:22:33:44:10\n  00:11:22:33:44:50\n"
                "port 5:1\n  00:11:22:33:44:11\n"
                "port 8:1\n  00:11:22:33:44:80\n"
            ),
            "show arp": (
                "LAN1 192.0.2.10 00:11:22:33:44:10 20\n"
                "LAN1 192.0.2.11 00:11:22:33:44:11 20\n"
                "LAN1 192.0.2.80 00:11:22:33:44:80 20\n"
            ),
        },
    }), encoding="utf-8")
    (config.ap_snapshot_directory / "ap1.json").write_text(json.dumps({
        "ap": "ap1", "collected_at": cycle_at + 30,
        "clients": [{"mac": "00:11:22:33:44:50", "hostname": "test-phone", "channel": "44"}],
    }), encoding="utf-8")
    (config.ap_snapshot_directory / "ap2.json").write_text(json.dumps({
        "ap": "ap2", "collected_at": cycle_at + 60, "clients": [],
    }), encoding="utf-8")
    config.pi_mac_file.write_text("00:11:22:33:44:80\n", encoding="utf-8")


def test_router_parsers_and_topology_do_not_misclassify_ap_clients() -> None:
    switch = "port 2:2\n  00:11:22:33:44:10\n  00:11:22:33:44:50\nport 8:1\n-- 00:11:22:33:44:80\n"
    assert parse_switch_ports(switch)["00:11:22:33:44:80"] == 8
    assert parse_switch_ports("port 7:0\n--            port 8:1\n     00:11:22:33:44:80\n")["00:11:22:33:44:80"] == 8
    assert parse_arp("LAN1 192.0.2.80 00:11:22:33:44:80 20\n") == {"00:11:22:33:44:80": "192.0.2.80"}
    config = Settings(Path("r"), Path("a"), Path("n"), Path("p"), Path("d"), Path("m"), (AP1, AP2))
    router = {"responses": {"show status switching-hub macaddress": switch, "show arp": "LAN1 192.0.2.10 00:11:22:33:44:10 20"}}
    aps = {"ap1": {"collected_at": 100.0, "clients": [{"mac": "00:11:22:33:44:50", "channel": "44"}]}, "ap2": None}
    nodes, edges = build_topology(config, router, aps, {}, "00:11:22:33:44:80")
    assert next(node for node in nodes if node["id"] == "mac001122334480")["title"] == "Raspberry Pi"
    assert next(node for node in nodes if node["id"] == "mac001122334450")["kind"] == "wifi"
    assert any(edge["source"] == "apap1" and edge["target"] == "mac001122334450" for edge in edges)
    assert not any(edge["target"] == "mac001122334410" for edge in edges)


def test_run_saves_single_cycle_and_rejects_stale_ap_snapshot(tmp_path: Path) -> None:
    config = settings(tmp_path)
    cycle_at = 1_700_000_100
    cycle_at -= cycle_at % 300
    write_inputs(config, cycle_at)
    assert run(config, cycle_at + 210)[0] >= 5
    assert run(config, cycle_at + 220)[0] >= 5
    with sqlite3.connect(config.database) as db:
        assert db.execute("SELECT count(*) FROM snapshot").fetchone()[0] == 1
        assert db.execute("SELECT status FROM source WHERE source_id='ap1'").fetchone()[0] == "observed"
        assert db.execute("SELECT count(*) FROM edge WHERE evidence='ap_association'").fetchone()[0] == 1
    assert config.database.stat().st_mode & 0o777 == 0o640
    assert 'home_lan_map_source_fresh{source="ap1"} 1' in config.metrics.read_text(encoding="utf-8")

    run(config, cycle_at + 510)
    with sqlite3.connect(config.database) as db:
        assert db.execute("SELECT count(*) FROM snapshot").fetchone()[0] == 2
        assert db.execute("SELECT status FROM source WHERE source_id='ap1' ORDER BY snapshot_id DESC LIMIT 1").fetchone()[0] == "unavailable"
        assert db.execute("SELECT count(*) FROM edge WHERE evidence='ap_association' AND snapshot_id=(SELECT max(id) FROM snapshot)").fetchone()[0] == 0


def test_dashboard_queries_select_historical_snapshot(tmp_path: Path) -> None:
    config = settings(tmp_path)
    cycle_at = 1_700_000_100
    cycle_at -= cycle_at % 300
    write_inputs(config, cycle_at)
    run(config, cycle_at + 210)
    run(config, cycle_at + 510)
    dashboard = json.loads((Path(__file__).parents[2] / "services/grafana/dashboards/lan-map/lan-map.json").read_text())
    graph = next(panel for panel in dashboard["panels"] if panel["type"] == "nodeGraph")
    query_time = str((cycle_at + 240) * 1000)
    with sqlite3.connect(config.database) as db:
        results = {}
        for target in graph["targets"]:
            cursor = db.execute(target["rawQueryText"].replace("$__to", query_time))
            results[target["refId"]] = (set(column[0] for column in cursor.description), cursor.fetchall())
    assert {"id", "title", "subtitle"} <= results["nodes"][0]
    assert {"id", "source", "target"} <= results["edges"][0]
    assert len(results["nodes"][1]) > 5
    assert len(results["edges"][1]) > 5
