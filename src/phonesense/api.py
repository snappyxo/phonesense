"""Importable API: run phonesense in-process and read frames directly.

    import phonesense
    cam = phonesense.start()        # server in a background daemon thread
    frame = cam.read()              # latest BGR numpy frame, or None (never blocks)
    ...
    cam.stop()

The same machine that runs your OpenCV code runs the server, so there's no
HTTPS hop, no self-signed-cert workaround, and no FFmpeg buffering on the
consumer side. The phone still connects over HTTPS + WebSocket as before.
"""

import asyncio
import ssl
import threading
import time

from aiohttp import web

from . import server, tls

# Ports started in this process, so a second start() on a busy port fails fast
# with a clear message instead of an opaque bind error.
_ACTIVE_PORTS = set()
_ACTIVE_LOCK = threading.Lock()


class Camera:
    """Handle to a running phonesense server. Returned by :func:`start`.

    Property = cheap snapshot of current state; method = does real work or has
    side effects. So ``jpeg``/``sensors``/``is_streaming`` and the URLs are
    properties, while ``read()`` (decodes) and ``stop()`` (acts) are methods.
    """

    def __init__(self, app, host, port, lan_ip, thread, loop):
        self._app = app
        self._thread = thread
        self._loop = loop
        self.host = host
        self.port = port
        self.lan_ip = lan_ip

    # -- connection info (fixed at start()) -------------------------------- #
    @property
    def base_url(self):
        return f"https://{self.lan_ip}:{self.port}"

    @property
    def dashboard_url(self):
        return f"{self.base_url}/"

    @property
    def phone_url(self):
        return f"{self.base_url}/phone"

    @property
    def ingest_url(self):
        return f"wss://{self.lan_ip}:{self.port}/ingest"

    @property
    def camera_url(self):
        return f"{self.base_url}/camera"

    @property
    def camera_stream_url(self):
        return f"{self.base_url}/camera/stream"

    @property
    def sensors_url(self):
        return f"{self.base_url}/sensors"

    @property
    def sensors_stream_url(self):
        return f"{self.base_url}/sensors/stream"

    @property
    def info_url(self):
        return f"{self.base_url}/info"

    @property
    def status_url(self):
        return f"{self.base_url}/status"

    @property
    def qr_url(self):
        return f"{self.base_url}/qr.svg"

    # -- live data --------------------------------------------------------- #
    def read(self):
        """Latest frame as a BGR numpy array, or ``None`` if none yet.

        Non-blocking — never waits for the phone. Decodes the stashed JPEG with
        OpenCV; if numpy/opencv aren't installed, raises ImportError pointing at
        :attr:`jpeg` (the dependency-free path).
        """
        data = self._app["latest_jpeg"]
        if data is None:
            return None
        try:
            import cv2
            import numpy as np
        except ImportError as exc:
            raise ImportError(
                "Camera.read() needs numpy + opencv to decode frames "
                "(`pip install opencv-python`). For raw bytes with no extra "
                "dependencies, use `cam.jpeg` instead."
            ) from exc
        return cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)

    @property
    def jpeg(self):
        """Latest raw JPEG bytes, or ``None`` (dependency-free)."""
        return self._app["latest_jpeg"]

    @property
    def sensors(self):
        """Latest sensor reading dict, or ``None``."""
        return self._app["latest_sensor"]

    @property
    def is_streaming(self):
        """True if a frame arrived in the last ~2s (mirrors /status)."""
        last = self._app["last_frame_mono"]
        if last is None:
            return False
        return (time.monotonic() - last) < 2.0

    # -- lifecycle --------------------------------------------------------- #
    def serve_forever(self):
        """Block the calling thread until the server stops (or Ctrl-C).

        The server itself runs on its own background thread; this just parks the
        caller. ``KeyboardInterrupt`` propagates so a CLI can call ``stop()``.
        """
        if self._thread is not None:
            self._thread.join()

    def stop(self):
        """Stop the server and join the background thread. Idempotent."""
        if self._loop is not None and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=10)
        with _ACTIVE_LOCK:
            _ACTIVE_PORTS.discard(self.port)
        self._loop = None
        self._thread = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.stop()
        return False


def start(port=8080, host="0.0.0.0", cert_dir=None, qr=True) -> Camera:
    """Start the phonesense server in a background daemon thread; return a Camera.

    Generates/loads the self-signed cert (``tls.ensure_cert``), builds the app
    (``server.build_app``), and runs it on a fresh event loop in a daemon
    thread. Returns once the listener is up. A second ``start()`` on a port
    already in use *in this process* raises a clear ``RuntimeError``.

    ``qr`` is accepted for signature parity with the CLI; the in-process API
    does not print a banner (the CLI does).
    """
    with _ACTIVE_LOCK:
        if port in _ACTIVE_PORTS:
            raise RuntimeError(
                f"phonesense is already running on port {port} in this process; "
                f"call stop() first or start() on a different port."
            )

    lan_ip = server.get_lan_ip()
    cert_path, key_path = tls.ensure_cert(lan_ip, cert_dir=cert_dir)

    ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_ctx.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))

    app = server.build_app()
    app["phone_url"] = f"https://{lan_ip}:{port}/phone"

    ready = threading.Event()
    box = {"error": None, "loop": None}

    def _run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        box["loop"] = loop
        runner = None
        try:
            runner = web.AppRunner(app)
            loop.run_until_complete(runner.setup())
            # shutdown_timeout bounds the graceful drain on stop(); the phone's
            # WebSocket and any MJPEG/SSE response are long-lived and never close
            # on their own, so the default 60s would hang stop(). Keep it short.
            site = web.TCPSite(runner, host=host, port=port, ssl_context=ssl_ctx,
                               shutdown_timeout=0.5)
            loop.run_until_complete(site.start())
        except Exception as exc:  # noqa: BLE001 — surfaced to start()'s caller
            box["error"] = exc
            ready.set()
            if runner is not None:
                loop.run_until_complete(runner.cleanup())
            loop.close()
            return
        ready.set()
        try:
            loop.run_forever()
        finally:
            loop.run_until_complete(_shutdown(runner))
            loop.close()

    thread = threading.Thread(target=_run, name="phonesense-server", daemon=True)
    thread.start()
    ready.wait()

    if box["error"] is not None:
        raise RuntimeError(
            f"phonesense failed to start on {host}:{port}: {box['error']}"
        ) from box["error"]

    with _ACTIVE_LOCK:
        _ACTIVE_PORTS.add(port)

    return Camera(app, host, port, lan_ip, thread, box["loop"])


async def _shutdown(runner):
    """Tear the server down fast on stop().

    The phone's WebSocket and any MJPEG/SSE response are long-lived and never
    close on their own, so a default cleanup would hang stop() (a frozen OpenCV
    window). ``TCPSite(shutdown_timeout=0.5)`` bounds the graceful drain, and the
    ``wait_for`` here is a final backstop against an SSL transport that won't
    close.
    """
    try:
        await asyncio.wait_for(runner.cleanup(), timeout=3)
    except Exception:  # noqa: BLE001 — forced shutdown, best-effort
        pass
