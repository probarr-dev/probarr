"""Stream sources. A source yields Stream objects; nothing downstream cares
which kind it came from."""
from .base import Stream, load_source          # noqa: F401
from . import m3u, dispatcharr, xtream          # noqa: F401
