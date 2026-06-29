"""Visual demo of the multi-homed pick flow (run by hand, not a test).

A machine with several network interfaces can't tell which one the phone is on,
so the CLI lists the addresses, asks you to pick, and then shows a single QR for
the chosen one. Most machines have a single IP, so this fakes a few extra
addresses purely to exercise the picker.

    python demo/multi_ip_banner.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from phonesense import cli
from phonesense.api import Camera

# Fake addresses for display only — none of these actually serve anything.
cam = Camera(None, "0.0.0.0", 8080,
             ["192.168.1.42", "10.0.0.5", "172.20.0.3"], None, None)

cam.select_ip(cli._choose_ip(cam.lan_ips))
print()
cli._print_banner(cam, qr=True)
