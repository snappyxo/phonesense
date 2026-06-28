#!/usr/bin/env python3
"""Verify the phonesense MJPEG stream is readable by OpenCV.

This is a standalone client of the server's /camera/stream endpoint — run it to
confirm the camera feed is available for OpenCV work. It does NOT do any ML; it
just proves frames arrive as normal BGR images.

Usage:
  python3 opencv_check.py                  # auto: https://<this-machine-LAN-IP>:8080/camera/stream
  python3 opencv_check.py <stream-url>     # explicit, e.g. https://192.168.1.42:8080/camera/stream
  python3 opencv_check.py --show           # live preview window, stays open until Esc
  python3 opencv_check.py --seconds 10     # sample 10s (default 5s headless)

Exit code 0 means OpenCV decoded frames successfully.
"""

# OpenCV's FFmpeg backend reads MJPEG over HTTP(S). FFmpeg does not verify TLS
# certs by default, so our self-signed cert is fine — but set this explicitly so
# it stays fine across FFmpeg builds. Must be set before importing cv2.
import os
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "tls_verify;0")

import argparse
import socket
import ssl
import sys
import time
import urllib.request

import cv2
import numpy as np

PORT = 8080


def lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def try_videocapture(url: str, seconds, show: bool) -> bool:
    """The classroom one-liner: cv2.VideoCapture(stream_url)."""
    print(f"[1] cv2.VideoCapture('{url}') …")
    cap = cv2.VideoCapture(url)
    if not cap.isOpened():
        print("    could not open the stream via VideoCapture.")
        return False
    return _drain(lambda: cap.read(), seconds, show, cap.release)


def try_manual(url: str, seconds, show: bool) -> bool:
    """Fallback: read the multipart MJPEG ourselves, decode with cv2.imdecode.

    Robust against any TLS/FFmpeg quirk because Python does the HTTPS.
    """
    print(f"[2] manual MJPEG reader on '{url}' …")
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        resp = urllib.request.urlopen(url, context=ctx, timeout=5)
    except Exception as e:  # noqa: BLE001
        print(f"    could not open the stream: {e}")
        return False

    buf = b""

    def read_frame():
        nonlocal buf
        while True:
            start = buf.find(b"\xff\xd8")  # JPEG SOI
            end = buf.find(b"\xff\xd9", start + 2)  # JPEG EOI
            if start != -1 and end != -1:
                jpg = buf[start:end + 2]
                buf = buf[end + 2:]
                img = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
                return (img is not None), img
            chunk = resp.read(4096)
            if not chunk:
                return False, None
            buf += chunk

    return _drain(read_frame, seconds, show, resp.close)


def _drain(read, seconds, show: bool, cleanup) -> bool:
    # seconds=None → run until Esc / stream ends (used with --show).
    frames, first_shape, t0, last = 0, None, time.time(), time.time()
    try:
        while seconds is None or time.time() - t0 < seconds:
            ok, frame = read()
            if not ok or frame is None:
                if time.time() - last > 5:
                    break
                continue
            frames += 1
            last = time.time()
            if first_shape is None:
                first_shape = frame.shape
            if show:
                cv2.imshow("phonesense (Esc to quit)", frame)
                if cv2.waitKey(1) == 27:
                    break
    finally:
        cleanup()
        if show:
            cv2.destroyAllWindows()

    if frames == 0:
        print("    opened, but decoded 0 frames (is the phone streaming?).")
        return False
    dt = time.time() - t0
    h, w = first_shape[0], first_shape[1]
    print(f"    OK — decoded {frames} frames at {w}x{h}, ~{frames / dt:.1f} fps.")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify the /camera/stream feed is OpenCV-readable.")
    ap.add_argument("url", nargs="?", help="stream URL (default https://<lan-ip>:8080/camera/stream)")
    ap.add_argument("--show", action="store_true",
                    help="open a live preview window (stays open until Esc)")
    ap.add_argument("--seconds", type=float, default=None,
                    help="seconds to sample (default 5 headless; unlimited with --show)")
    args = ap.parse_args()

    # With --show, keep the window open until Esc unless a limit was given.
    seconds = args.seconds if args.seconds is not None else (None if args.show else 5.0)

    url = args.url or f"https://{lan_ip()}:{PORT}/camera/stream"
    print(f"Checking feed: {url}\n")

    if try_videocapture(url, seconds, args.show):
        print("\n✅ OpenCV can read the feed with the standard one-liner:")
        print(f'   cap = cv2.VideoCapture("{url}")')
        return 0

    print("\n    VideoCapture didn't work here; trying the manual reader…\n")
    if try_manual(url, seconds, args.show):
        print("\n✅ The feed is OpenCV-readable via the manual MJPEG reader.")
        print("   (Use the read_frame() approach from this script — copy try_manual().)")
        return 0

    print("\n❌ Could not read any frames. Checklist:")
    print("   • Is the server running?  uvx phonesense")
    print("   • Is a phone (or the /phone tab) actively Streaming?")
    print("   • Right IP/port, same LAN?")
    return 1


if __name__ == "__main__":
    sys.exit(main())
