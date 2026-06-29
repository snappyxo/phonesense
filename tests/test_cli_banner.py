"""Connection-info presentation: ``Camera`` URLs, ``select_ip``, and the banner.

After a multi-homed host picks an address, every derived URL and the banner must
follow the choice, and the unpicked addresses stay visible as a fallback hint.
"""

import contextlib
import io

from phonesense import cli
from phonesense.api import Camera


def _camera(lan_ips, port=8080, app=None):
    return Camera(app, "0.0.0.0", port, lan_ips, None, None)


def _banner(cam):
    """Render the banner (QR off) and return its text."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cli._print_banner(cam, qr=False)
    return buf.getvalue()


def test_primary_is_first_candidate():
    cam = _camera(["192.168.1.42", "10.0.0.5"])
    assert cam.lan_ip == "192.168.1.42"
    assert cam.base_url == "https://192.168.1.42:8080"


def test_phone_urls_one_per_candidate():
    cam = _camera(["192.168.1.42", "10.0.0.5"])
    assert cam.phone_urls == [
        "https://192.168.1.42:8080/phone",
        "https://10.0.0.5:8080/phone",
    ]


def test_select_ip_repoints_every_url_and_app():
    app = {"phone_url": "https://192.168.1.42:8080/phone"}
    cam = _camera(["192.168.1.42", "10.0.0.5"], app=app)
    cam.select_ip("10.0.0.5")
    assert cam.lan_ip == "10.0.0.5"
    assert cam.base_url == "https://10.0.0.5:8080"
    assert cam.camera_stream_url == "https://10.0.0.5:8080/camera/stream"
    assert app["phone_url"] == "https://10.0.0.5:8080/phone"


def test_select_ip_rejects_unknown_address():
    cam = _camera(["192.168.1.42", "10.0.0.5"])
    try:
        cam.select_ip("203.0.113.9")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for an address not in lan_ips")


def test_banner_shows_the_chosen_address_with_one_phone_url():
    cam = _camera(["192.168.1.42", "10.0.0.5"])
    cam.select_ip("10.0.0.5")
    out = _banner(cam)
    assert "https://10.0.0.5:8080/phone" in out
    # The unpicked address is a fallback hint, not a second phone link.
    assert "https://192.168.1.42:8080/phone" not in out


def test_banner_lists_other_addresses_as_a_hint():
    out = _banner(_camera(["192.168.1.42", "10.0.0.5", "172.20.0.3"]))
    assert "Other addresses on this machine" in out
    assert "10.0.0.5" in out
    assert "172.20.0.3" in out


def test_banner_single_homed_has_no_other_addresses():
    out = _banner(_camera(["192.168.1.42"]))
    assert "Other addresses" not in out
    assert "10.0.0.5" not in out


def test_banner_always_warns_to_use_local_wifi():
    assert "Wi-Fi" in _banner(_camera(["192.168.1.42"]))
    assert "Wi-Fi" in _banner(_camera(["192.168.1.42", "10.0.0.5"]))
