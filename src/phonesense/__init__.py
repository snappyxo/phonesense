"""phonesense — turn a phone into a LAN camera + motion-sensor source.

Two ways to use it:

  1. In-process (recommended, same machine)::

         import phonesense
         cam = phonesense.start()
         frame = cam.read()          # latest BGR numpy frame, or None

  2. Standalone server::

         uvx phonesense              # or: pipx run phonesense

See ``phonesense.start`` and the ``Camera`` handle it returns.
"""

from .api import Camera, start

__version__ = "0.1.0"

__all__ = ["start", "Camera", "__version__"]
