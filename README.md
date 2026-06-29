# phonesense

Turn a phone into a LAN camera + motion-sensor source for Python/OpenCV — one
line, no app to install. The phone's browser captures the camera and motion
sensors and pushes them over your local network; your Python code reads frames
and sensor data with zero setup on the phone.

Built for STEM classrooms where students write Python/OpenCV against a live
camera, but useful anywhere you want a quick wireless webcam.

## Two ways to use it

### 1. In-process (recommended, same machine)

Start the server from inside your OpenCV script and read frames directly — no
separate process, no HTTPS hop, no self-signed-cert workaround:

```python
import phonesense, cv2, numpy as np

cam = phonesense.start()                 # server starts in a background thread
print("On your phone, open:", cam.phone_url)   # scan the QR the CLI prints, or type the URL

while True:
    jpeg = cam.jpeg                      # latest JPEG bytes, or None until the phone connects
    if jpeg is not None:
        frame = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        cv2.imshow("phone", frame)
    if cv2.waitKey(1) == 27:             # Esc to quit
        break

cam.stop()
```

phonesense hands you JPEG bytes and depends on no imaging library — decode with
OpenCV (above), Pillow, or anything else. `cam.jpeg` never blocks: it returns the
latest frame's bytes, or `None` until the phone has sent one.

### 2. Standalone server

Run the server on its own and point any consumer at it:

```sh
uvx phonesense          # or: pipx run phonesense
```

It prints the LAN URLs and a scannable QR code. Open the phone page, tap
**Start**, and watch the dashboard.

```
phonesense --port 8080 --host 0.0.0.0 --no-qr --cert-dir ./certs
```

## On the phone

1. Open `https://<your-lan-ip>:8080/phone` (scan the printed QR to skip typing).
2. Tap through the one-time certificate warning (the cert is self-signed).
3. Tap **Start** — the dashboard at `https://<your-lan-ip>:8080/` shows live
   video. **Enable sensors** streams motion data.

> No phone handy? Open `/phone` in a second browser tab on the computer to use
> the computer's webcam instead.

## OpenCV: snapshot vs stream

`phonesense` exposes each data type two ways — a **live stream** (follow every
new value) and a **snapshot** (one current value per request).

For **same-machine** use, the in-process API beats every HTTP route:
`cam.jpeg` (raw bytes), `cam.sensors` (dict) have no
HTTPS hop, no cert workaround, and no buffering. The HTTP endpoints below are
the **off-machine** (or non-Python) paths.

### Camera — `/camera/stream` vs `/camera`

| | `/camera/stream` (MJPEG) | `/camera` (single JPEG) |
|---|---|---|
| Model | continuous push | one request → one frame (poll) |
| OpenCV | `cv2.VideoCapture(url)` + loop `.read()` | `requests.get` + `cv2.imdecode` |
| Throughput | high (one open connection) | low (a request per frame) |
| Latency | low, but FFmpeg may buffer a few frames | always the freshest single frame |
| Cert | needs `OPENCV_FFMPEG_CAPTURE_OPTIONS=tls_verify;0` | handled in Python (`requests(..., verify=...)`) |
| Use for | live video processing | thumbnails, periodic checks, `curl`/debug |

Continuous MJPEG into OpenCV (the off-machine one-liner):

```sh
OPENCV_FFMPEG_CAPTURE_OPTIONS=tls_verify;0 \
  python -c "import cv2; c=cv2.VideoCapture('https://<ip>:8080/camera/stream'); print(c.read()[0], c.read()[1].shape)"
```

Single frame, decoded yourself (no FFmpeg, control your own TLS):

```python
import requests, numpy as np, cv2
r = requests.get('https://<ip>:8080/camera', verify=False)
frame = cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_COLOR)
```

### Sensors — `/sensors/stream` vs `/sensors`

| | `/sensors/stream` (SSE) | `/sensors` (single JSON) |
|---|---|---|
| Model | continuous push (Server-Sent Events) | one request → latest reading (poll) |
| Consume | SSE client, or read `data:` lines | `requests.get(...).json()` |
| Best for | smooth live charts, event-driven loops | one-off "what's the current tilt?" |

```python
import requests
print(requests.get('https://<ip>:8080/sensors', verify=False).json())   # snapshot
```

A fuller OpenCV reachability check is in
[`examples/opencv_check.py`](examples/opencv_check.py).

## Examples

Runnable scripts in [`examples/`](examples/):

| File | Shows |
|---|---|
| [`opencv_import.py`](examples/opencv_import.py) | in-process — `phonesense.start()` + `cam.jpeg` decode loop (recommended, same machine) |
| [`opencv_url.py`](examples/opencv_url.py) | off-machine — `cv2.VideoCapture('https://<ip>:8080/camera/stream')` loop |
| [`opencv_check.py`](examples/opencv_check.py) | diagnostic — confirms the feed is OpenCV-readable, with a manual-MJPEG fallback and a troubleshooting checklist |

## The `Camera` handle

`phonesense.start(port=8080, host="0.0.0.0", cert_dir=None, qr=True)` returns a
`Camera`:

| Member | Kind | Returns / does |
|---|---|---|
| `jpeg` | property | latest frame as raw JPEG bytes, or `None` (non-blocking) |
| `sensors` | property | latest sensor dict, or `None` |
| `is_streaming` | property | `True` if a frame arrived in the last ~2s |
| `base_url`, `phone_url`, `dashboard_url`, `ingest_url`, `camera_url`, `camera_stream_url`, `sensors_url`, `sensors_stream_url`, `info_url`, `status_url`, `qr_url` | properties | the route URLs |
| `lan_ip`, `host`, `port` | attributes | URL components |
| `stop()` | method | stop the server, join the thread |
| `with ... as cam:` | context manager | `stop()` on exit |

phonesense depends on **no imaging library** — it transports JPEG bytes and
leaves decoding to you. Decode `cam.jpeg` with OpenCV
(`cv2.imdecode(np.frombuffer(cam.jpeg, np.uint8), cv2.IMREAD_COLOR)`), Pillow, or
anything else.

## Routes

| Route | Purpose |
|---|---|
| `/` | dashboard |
| `/phone` | phone capture page |
| `/ingest` | phone upload (WebSocket: JPEG frames + sensor JSON) |
| `/camera` | latest single JPEG |
| `/camera/stream` | live MJPEG (the `cv2.VideoCapture` URL) |
| `/sensors` | latest sensor reading (JSON) |
| `/sensors/stream` | live sensor stream (SSE) |
| `/info`, `/status` | dashboard connection info + liveness |
| `/qr.svg` | QR code for the phone URL |

Scheme: `/X` = latest single value, `/X/stream` = live stream, `/ingest` = the
phone's upload.

## Architecture

The phone's browser captures JPEG frames + sensor JSON and pushes them over one
WebSocket (`/ingest`). A latest-value hub fans each new value out to every
consumer: frames to `/camera/stream` (MJPEG) and the in-process API, sensors to
`/sensors/stream` (SSE). Only one phone streams at a time — a new connection
takes over the previous one, so two phones never mix into one feed.

HTTPS is required because browsers only expose the camera over a secure origin.
The cert is self-signed, generated in pure Python (no system `openssl`) and
cached in a per-user data dir so it isn't regenerated each run.

## Future: WebRTC

The current transport (WebSocket upload + MJPEG/SSE out) is simple, low-latency
on a LAN, and keeps the one-line OpenCV ingestion. For HD / high-FPS, or to drop
the certificate tap entirely, a WebRTC ingest path can publish into the same hub
without touching `/camera/stream`, the in-process API, or any consumer — the
boundary is already isolated in the upload handler.

## License

MIT — see [LICENSE](LICENSE).
