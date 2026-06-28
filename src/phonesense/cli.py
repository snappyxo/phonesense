"""Command-line entry point: a thin wrapper over :func:`phonesense.start`.

Starts the same server the importable API runs, prints the connection banner
(URLs + a scannable terminal QR), then blocks until Ctrl-C.
"""

import argparse
import sys

import segno

from . import __version__
from .api import start


def _print_banner(cam, qr=True):
    line = "=" * 60
    print(line)
    print(f"  phonesense {__version__}")
    print(f"  Listening on  {cam.base_url}")
    print(f"  Phone page    {cam.phone_url}")
    print(f"  Live feed     {cam.camera_stream_url}")
    print(f"  Dashboard     {cam.dashboard_url}")
    print(line)
    if qr:
        print("  Scan this with the phone's camera to open the page:\n")
        segno.make(cam.phone_url, error="m").terminal(compact=True)
        print()
    print("  (Tap through the one-time certificate warning on the phone.)")
    print("  Press Ctrl-C to stop.")


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="phonesense",
        description="Turn a phone into a LAN camera + motion-sensor source for OpenCV.",
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

    _print_banner(cam, qr=not args.no_qr)

    try:
        cam.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping…")
        cam.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
