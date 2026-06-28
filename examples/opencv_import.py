#!/usr/bin/env python3
"""Use phonesense in-process (recommended, same machine).

Start the server from inside your script and read frames directly — no separate
process, no HTTPS hop, no self-signed-cert workaround. `cam.read()` is
non-blocking: it returns the latest BGR frame, or None until the phone connects.

Run:
  python3 examples/opencv_import.py

Then open the printed URL on your phone (or scan the QR the CLI shows) and tap
Start. Press Esc in the preview window to quit.
"""

import cv2

import phonesense

cam = phonesense.start()
print("On your phone, open:", cam.phone_url)
print("Waiting for frames… (Esc in the window to quit)")

try:
    while True:
        frame = cam.read()            # latest BGR frame, or None — never blocks
        if frame is not None:
            cv2.imshow("phonesense (import) - Esc to quit", frame)
        if cv2.waitKey(1) == 27:      # Esc
            break
finally:
    cv2.destroyAllWindows()
    cv2.waitKey(1)          # let the window actually close before we block on stop()
    cam.stop()
