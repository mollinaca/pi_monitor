import pytest

from pi_wifi_probe.parsers import frequency_to_channel, parse_link, parse_ping


@pytest.mark.parametrize(
    ("frequency", "channel"),
    [(2412, 1), (2462, 11), (2484, 14), (5520, 104), (5540, 108)],
)
def test_frequency_to_channel(frequency: int, channel: int) -> None:
    assert frequency_to_channel(frequency) == channel


def test_parse_ping() -> None:
    output = """
5 packets transmitted, 5 received, 0% packet loss, time 4006ms
rtt min/avg/max/mdev = 2.172/4.368/5.536/1.156 ms
"""
    result = parse_ping(output)
    assert result.packet_loss_ratio == 0
    assert result.average_seconds == pytest.approx(0.004368)


def test_parse_link() -> None:
    link = """
Connected to 00:00:00:00:00:00 (on wlan0)
    freq: 5520
    signal: -73 dBm
    rx bitrate: 6.5 MBit/s
    tx bitrate: 292.5 MBit/s
"""
    station = """
    signal: -72 dBm
    tx bitrate: 300.0 MBit/s
    rx bitrate: 12.0 MBit/s
    tx failed: 2
"""
    result = parse_link(link, station)
    assert result.signal_dbm == -72
    assert result.frequency_mhz == 5520
    assert result.channel == 104
    assert result.rx_bitrate_mbps == 12
    assert result.tx_bitrate_mbps == 300
    assert result.tx_failed_packets == 2
