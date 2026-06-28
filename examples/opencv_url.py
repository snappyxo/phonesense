#!/usr/bin/env python3
"""Read the phonesense feed over the network with cv2.VideoCapture (off-machine).

Use this when the OpenCV code runs on a *different* machine than the server (or
in a non-Python tool). On the same machine, prefer opencv_import.py — it avoids
the HTTPS hop, the cert workaround, and FFmpeg buffering.

Run the server somewhere (`uvx phonesense`), note the "Live feed" URL it prints,
then:

  python3 examples/opencv_url.py https://<lan-ip>:8080/camera/stream

Press Esc in the preview window to quit.
"""

# OpenCV's FFmpeg backend reads MJPEG over HTTPS but won't verify our
# self-signed cert — tell it to skip verification. Must be set before cv2 is
# imported.
import os
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "tls_verify;0")

import sys

if len(sys.argv) < 2:
    sys.exit(
        "usage: python3 examples/opencv_url.py <stream-url>\n"
        "       e.g. https://192.168.1.42:8080/camera/stream\n"
        "       (the server prints this as the 'Live feed' URL)"
    )

import cv2

url = sys.argv[1]
cap = cv2.VideoCapture(url)            # the one-liner students write
if not cap.isOpened():
    sys.exit(f"could not open {url} — is the server running and a phone streaming?")

print(f"Reading {url} … (Esc in the window to quit)")
try:
    while True:
        ok, frame = cap.read()
        if not ok:
            print("stream ended")
            break
        cv2.imshow("phonesense (url) - Esc to quit", frame)
        if cv2.waitKey(1) == 27:      # Esc
            break
finally:
    cv2.destroyAllWindows()
    cv2.waitKey(1)          # let the window actually close before releasing the stream
    cap.release()
