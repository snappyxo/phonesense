#!/usr/bin/env python3
"""Use phonesense in-process (recommended, same machine).

Start the server from inside your script and grab frames directly — no separate
process, no HTTPS hop, no self-signed-cert workaround. `cam.jpeg` is
non-blocking: it returns the latest JPEG bytes, or None until the phone connects.
phonesense hands you bytes; you decode with whatever you like (here, OpenCV).

Run:
  python3 examples/opencv_import.py

Then open the printed URL on your phone (or scan the QR the CLI shows) and tap
Start. Press Esc in the preview window to quit.
"""

import cv2
import numpy as np

import phonesense

cam = phonesense.start()
print("On your phone, open:", cam.phone_url)
print("Waiting for frames… (Esc in the window to quit)")

try:
    while True:
        jpeg = cam.jpeg               # latest JPEG bytes, or None — never blocks
        if jpeg is not None:
            frame = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
            cv2.imshow("phonesense (import) - Esc to quit", frame)
        if cv2.waitKey(1) == 27:      # Esc
            break
finally:
    cv2.destroyAllWindows()
    cv2.waitKey(1)          # let the window actually close before we block on stop()
    cam.stop()
