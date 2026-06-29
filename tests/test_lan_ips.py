"""LAN IP enumeration (``server.get_lan_ips`` / ``server.get_lan_ip``).

These guard the design's core guarantee: every usable address on the host is
offered, default-route IP first, so a phone always has the address on its own
subnet to reach — rather than a single guessed one.
"""

import socket
from collections import namedtuple

from phonesense import server

# Mirror of psutil's snicaddr (family, address, netmask, broadcast, ptp).
_Snic = namedtuple("snicaddr", ["family", "address", "netmask", "broadcast", "ptp"])


def _ipv4(ip):
    return _Snic(socket.AF_INET, ip, None, None, None)


def _ipv6(ip):
    return _Snic(socket.AF_INET6, ip, None, None, None)


class _FakeUDPSocket:
    """Stand-in for the routing-probe socket; ``connect()`` sends nothing."""

    def __init__(self, primary, fail):
        self._primary = primary
        self._fail = fail

    def connect(self, addr):
        if self._fail:
            raise OSError("no route to host")

    def getsockname(self):
        return (self._primary, 0)

    def close(self):
        pass


def _patch_addrs(monkeypatch, primary, iface_addrs, connect_fails=False):
    """Drive get_lan_ips(): a controlled default-route IP + per-interface addrs.

    ``iface_addrs`` are the snicaddr entries psutil would report across all
    interfaces (use _ipv4/_ipv6 helpers).
    """
    monkeypatch.setattr(server.socket, "socket",
                        lambda family, type: _FakeUDPSocket(primary, connect_fails))
    monkeypatch.setattr(server.psutil, "net_if_addrs",
                        lambda: {"iface0": list(iface_addrs)})


def test_default_route_ip_comes_first(monkeypatch):
    # psutil reports both, unordered; the default-route IP must still rank first.
    _patch_addrs(monkeypatch, "192.168.1.42", [_ipv4("10.0.0.5"), _ipv4("192.168.1.42")])
    assert server.get_lan_ips() == ["192.168.1.42", "10.0.0.5"]


def test_enumerates_every_interface(monkeypatch):
    _patch_addrs(monkeypatch, "192.168.1.42",
                 [_ipv4("192.168.1.42"), _ipv4("10.0.0.5"), _ipv4("172.20.0.3")])
    assert server.get_lan_ips() == ["192.168.1.42", "10.0.0.5", "172.20.0.3"]


def test_drops_loopback_link_local_unspecified_and_ipv6(monkeypatch):
    _patch_addrs(monkeypatch, "192.168.1.42",
                 [_ipv4("127.0.0.1"), _ipv4("169.254.7.7"), _ipv4("0.0.0.0"),
                  _ipv6("fe80::1"), _ipv4("10.0.0.5")])
    assert server.get_lan_ips() == ["192.168.1.42", "10.0.0.5"]


def test_dedups_primary_against_interface_addrs(monkeypatch):
    _patch_addrs(monkeypatch, "192.168.1.42", [_ipv4("192.168.1.42"), _ipv4("10.0.0.5")])
    assert server.get_lan_ips() == ["192.168.1.42", "10.0.0.5"]


def test_falls_back_to_loopback_when_nothing_usable(monkeypatch):
    _patch_addrs(monkeypatch, "0.0.0.0", [_ipv4("127.0.0.1")], connect_fails=True)
    assert server.get_lan_ips() == ["127.0.0.1"]


def test_get_lan_ip_returns_first_candidate(monkeypatch):
    monkeypatch.setattr(server, "get_lan_ips", lambda: ["1.2.3.4", "5.6.7.8"])
    assert server.get_lan_ip() == "1.2.3.4"
