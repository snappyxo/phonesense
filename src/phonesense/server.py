"""phonesense streaming hub — aiohttp app, routes, and the latest-value hub.

One app that:
  - serves the phone capture page at /phone,
  - ingests JPEG frames + sensor JSON from the phone over a WebSocket at /ingest,
  - re-serves the latest frame as MJPEG at /camera/stream (for OpenCV) and as a
    single JPEG at /camera, and the latest sensor reading at /sensors (snapshot)
    and /sensors/stream (SSE),
  - runs over self-signed HTTPS (required for the phone's camera APIs).

Transport seam (future WebRTC): the phone's upload is isolated in ``stream_ws``,
which only calls ``hub.publish(frame)`` / ``sensor_hub.publish(reading)`` and
stashes the latest values on the app. A future ``webrtc.py`` ingest can publish
into the same hubs, leaving /camera/stream, /sensors/stream, and the in-process
API untouched. No abstraction layer is built now — the boundary is just kept
clean.

Route scheme: /X = latest single value, /X/stream = live stream out, /ingest =
the phone's upload (frames + sensors over one WebSocket).
"""

import asyncio
import io
import ipaddress
import json
import socket
import time
from importlib.resources import files

import psutil
import segno
from aiohttp import WSCloseCode, WSMsgType, web

WEB_DIR = files("phonesense") / "web"


# --------------------------------------------------------------------------- #
# Latest-value hub: one publisher (the phone), many subscribers. Used for both
# the JPEG frame stream (/camera/stream) and the sensor stream (/sensors/stream).
# --------------------------------------------------------------------------- #
class LatestHub:
    """Holds the latest value and wakes every subscriber when it changes."""

    def __init__(self):
        self._latest = None
        self._seq = 0
        self._cond = asyncio.Condition()

    @property
    def latest(self):
        return self._latest

    async def publish(self, value):
        async with self._cond:
            self._latest = value
            self._seq += 1
            self._cond.notify_all()

    async def subscribe(self):
        """Yield each new value as it arrives. Skips values a slow consumer missed."""
        last_seq = self._seq
        while True:
            async with self._cond:
                await self._cond.wait_for(lambda: self._seq != last_seq)
                last_seq = self._seq
                value = self._latest
            yield value


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
# The phone and dashboard pages are tiny and change between releases, so serve
# them no-cache — otherwise a phone keeps showing a stale capture page after an
# upgrade (e.g. old button labels / behavior).
_NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate"}


async def phone_page(request):
    return web.FileResponse(WEB_DIR / "phone.html", headers=_NO_CACHE)


async def index_page(request):
    return web.FileResponse(WEB_DIR / "dashboard.html", headers=_NO_CACHE)


async def info_json(request):
    """Connection details for the dashboard (so it can show the URL as text)."""
    return web.json_response({"phone_url": request.app["phone_url"]})


async def status_json(request):
    """Connection + per-feed liveness for the dashboard.

    ``connected`` is the phone's WebSocket being open — it drives the dashboard's
    QR-gate-vs-panels split, independent of whether any data is flowing yet.
    ``camera``/``sensors`` say whether that feed produced something in the last
    ~2s, so each panel can show its data or a "no data" message.
    """
    app = request.app
    active = app["active_ws"]
    connected = active is not None and not active.closed
    now = time.monotonic()
    fmono, smono = app["last_frame_mono"], app["last_sensor_mono"]
    cam = fmono is not None and (now - fmono) < 2.0
    sens = smono is not None and (now - smono) < 2.0
    return web.json_response({
        "connected": connected,
        "camera": cam,
        "sensors": sens,
    })


async def camera_snapshot(request):
    """Latest single JPEG frame (the camera mirror of /sensors). 503 until one arrives."""
    frame = request.app["latest_jpeg"]
    if frame is None:
        return web.Response(status=503, text="no frame yet")
    return web.Response(
        body=frame,
        content_type="image/jpeg",
        headers={"Cache-Control": "no-cache, private", "Pragma": "no-cache"},
    )


async def sensors_json(request):
    """Latest motion-sensor reading the phone sent (null until one arrives)."""
    return web.json_response(request.app["sensor_hub"].latest)


async def sensors_sse(request):
    """Server-Sent Events: push every new sensor reading for smooth live charts."""
    resp = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
    await resp.prepare(request)
    sensor_hub: LatestHub = request.app["sensor_hub"]
    try:
        # Send the current value immediately so a fresh tab isn't blank.
        if sensor_hub.latest is not None:
            await resp.write(b"data: " + json.dumps(sensor_hub.latest).encode() + b"\n\n")
        async for reading in sensor_hub.subscribe():
            await resp.write(b"data: " + json.dumps(reading).encode() + b"\n\n")
    except (ConnectionResetError, asyncio.CancelledError):
        pass
    return resp


async def qr_svg(request):
    """QR code for the phone page URL — scan it to skip typing the IP."""
    qr = segno.make(request.app["phone_url"], error="m")
    buf = io.BytesIO()
    qr.save(buf, kind="svg", scale=6, border=2, dark="#111", light="#fff")
    return web.Response(
        body=buf.getvalue(),
        content_type="image/svg+xml",
        headers={"Cache-Control": "no-cache"},
    )


async def stream_ws(request):
    """Phone uploads here. Binary message = JPEG frame; text = sensor JSON.

    Single-phone policy: only one phone streams at a time. A new connection takes
    over and the previous socket is closed, so two phones can never mix into the
    one feed. (Takeover, not reject, keeps a reloading/reconnecting phone working.)
    """
    ws = web.WebSocketResponse(max_msg_size=16 * 1024 * 1024, heartbeat=10)
    await ws.prepare(request)
    peer = request.remote

    old = request.app["active_ws"]
    if old is not None and not old.closed:
        print(f"[ingest] new phone {peer} takes over; closing previous connection")
        try:
            await old.close(code=WSCloseCode.GOING_AWAY,
                            message=b"replaced by a newer connection")
        except Exception:  # noqa: BLE001
            pass
    request.app["active_ws"] = ws

    print(f"[ingest] phone connected: {peer}")
    hub: LatestHub = request.app["hub"]
    sensor_hub: LatestHub = request.app["sensor_hub"]
    try:
        async for msg in ws:
            if msg.type == WSMsgType.BINARY:
                await hub.publish(msg.data)
                # Stash for cross-thread sync readers (api.Camera). A bare
                # reference assignment is atomic in CPython — no lock needed for
                # a single-writer/single-reader snapshot.
                request.app["latest_jpeg"] = msg.data
                request.app["last_frame_mono"] = time.monotonic()
            elif msg.type == WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                except ValueError:
                    continue
                if data.get("type") == "sensor":
                    await sensor_hub.publish(data)
                    request.app["latest_sensor"] = data
                    request.app["last_sensor_mono"] = time.monotonic()
            elif msg.type == WSMsgType.ERROR:
                print(f"[ingest] ws error: {ws.exception()}")
    finally:
        # Only clear the slot if we're still the active phone (a takeover may
        # have already replaced us).
        if request.app["active_ws"] is ws:
            request.app["active_ws"] = None
        print(f"[ingest] phone disconnected: {peer}")
    return ws


async def feed_mjpeg(request):
    """Re-serve the latest frames as multipart MJPEG (pass-through, no re-encode)."""
    boundary = "frame"
    resp = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": f"multipart/x-mixed-replace; boundary={boundary}",
            "Cache-Control": "no-cache, private",
            "Pragma": "no-cache",
        },
    )
    await resp.prepare(request)
    hub: LatestHub = request.app["hub"]
    try:
        async for frame in hub.subscribe():
            await resp.write(
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(frame)).encode() + b"\r\n\r\n"
                + frame + b"\r\n"
            )
    except (ConnectionResetError, asyncio.CancelledError):
        pass
    return resp


# --------------------------------------------------------------------------- #
# Networking helper
# --------------------------------------------------------------------------- #
def get_lan_ips() -> list[str]:
    """Every usable LAN IPv4 address on this host, best guess first.

    The first entry is the source IP the OS would use to reach an external host
    — the default-route interface, which is the right address on a single-network
    machine. Every other IPv4 address bound to a real interface follows, so a phone
    on a different interface's subnet (a second NIC, a separate Wi-Fi) always has
    its reachable address offered rather than guessed away. Loopback, link-local
    and unspecified addresses are dropped. Falls back to ``["127.0.0.1"]`` if
    nothing usable is found.

    No packets are sent: ``connect()`` on a UDP socket only primes the routing
    table so ``getsockname()`` reports the chosen source IP.
    """
    candidates: list[str] = []

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        candidates.append(s.getsockname()[0])
    except OSError:
        pass
    finally:
        s.close()

    # Every IPv4 address on every interface — psutil enumerates them the same way
    # on each OS, so a second NIC or Wi-Fi on a different subnet is never missed.
    for addrs in psutil.net_if_addrs().values():
        for addr in addrs:
            if addr.family == socket.AF_INET:
                candidates.append(addr.address)

    usable: list[str] = []
    for ip in candidates:
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if addr.is_loopback or addr.is_link_local or addr.is_unspecified:
            continue
        if ip not in usable:
            usable.append(ip)

    return usable or ["127.0.0.1"]


def get_lan_ip() -> str:
    """Best-effort primary LAN IP — the default-route address from get_lan_ips()."""
    return get_lan_ips()[0]


def build_app() -> web.Application:
    app = web.Application()
    app["hub"] = LatestHub()         # latest JPEG frame (drives /camera/stream)
    app["sensor_hub"] = LatestHub()  # latest sensor reading (drives /sensors/stream)
    app["last_frame_mono"] = None    # monotonic time of the last frame received
    app["last_sensor_mono"] = None   # monotonic time of the last sensor reading received
    app["active_ws"] = None          # the one phone currently streaming (single-phone policy)
    app["latest_jpeg"] = None        # latest JPEG bytes, for cross-thread sync readers
    app["latest_sensor"] = None      # latest sensor dict, for cross-thread sync readers
    app.add_routes([
        web.get("/", index_page),
        web.get("/phone", phone_page),
        web.get("/ingest", stream_ws),
        web.get("/camera", camera_snapshot),
        web.get("/camera/stream", feed_mjpeg),
        web.get("/sensors", sensors_json),
        web.get("/sensors/stream", sensors_sse),
        web.get("/info", info_json),
        web.get("/status", status_json),
        web.get("/qr.svg", qr_svg),
    ])
    return app
