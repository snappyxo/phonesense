"""Command-line entry point: a thin wrapper over :func:`phonesense.start`.

Starts the same server the importable API runs, prints the connection banner
(URLs + a scannable terminal QR), then blocks until Ctrl-C.
"""

import argparse
import sys

import segno

from . import __version__
from .api import start


def _choose_ip(lan_ips):
    """Prompt for which LAN address to advertise; return the chosen IP.

    Used for a multi-homed host on an interactive terminal: we can't tell which
    interface the phone is on, so the user picks. Enter (or EOF) takes the first,
    default address.
    """
    print("  This computer has several network addresses.")
    print("  Pick the one on the same network as your phone:\n")
    for i, ip in enumerate(lan_ips, 1):
        suffix = "  (default)" if i == 1 else ""
        print(f"    {i}) {ip}{suffix}")
    print()
    while True:
        try:
            raw = input(f"  Choice [1-{len(lan_ips)}, Enter = 1]: ").strip()
        except EOFError:
            print()
            return lan_ips[0]
        if not raw:
            return lan_ips[0]
        if raw.isdigit() and 1 <= int(raw) <= len(lan_ips):
            return lan_ips[int(raw) - 1]
        print("  Enter a number from the list.")


def _print_banner(cam, qr=True):
    line = "=" * 60
    print(line)
    print(f"  phonesense {__version__}")
    print(f"  Listening on  {cam.base_url}")
    print(f"  Phone page    {cam.phone_url}")
    print(f"  Live feed     {cam.camera_stream_url}")
    print(f"  Dashboard     {cam.dashboard_url}")
    print(line)
    print("  Connect the phone to the same Wi-Fi as this computer "
          "(not cellular).")
    others = [ip for ip in cam.lan_ips if ip != cam.lan_ip]
    if others:
        print(f"  Other addresses on this machine: {', '.join(others)}")
        print("  (restart and pick another if the phone can't reach this one)")
    if qr:
        print("\n  Scan this with the phone's camera to open the page:\n")
        segno.make(cam.phone_url, error="m").terminal(compact=True)
        print()
    print("  (Tap through the one-time certificate warning on the phone.)")
    print("  Press Ctrl-C to stop.")


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="phonesense",
        description="Turn a phone into a LAN camera + motion-sensor source for Python.",
    )
    parser.add_argument("--port", type=int, default=8080, help="port to listen on (default 8080)")
    parser.add_argument("--host", default="0.0.0.0", help="host/interface to bind (default 0.0.0.0)")
    parser.add_argument("--cert-dir", default=None,
                        help="directory for cert.pem/key.pem (default: per-user data dir)")
    parser.add_argument("--no-qr", action="store_true", help="don't print the terminal QR code")
    parser.add_argument("--version", action="version", version=f"phonesense {__version__}")
    args = parser.parse_args(argv)

    try:
        cam = start(port=args.port, host=args.host, cert_dir=args.cert_dir, qr=not args.no_qr)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    # Multi-homed host: let the user pick which address to advertise before the
    # QR. Non-interactive (piped) runs can't prompt, so they keep the default.
    if len(cam.lan_ips) > 1 and sys.stdin.isatty():
        cam.select_ip(_choose_ip(cam.lan_ips))

    _print_banner(cam, qr=not args.no_qr)

    try:
        cam.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping…")
        cam.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
