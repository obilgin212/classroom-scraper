"""classroom-parser: read your own Google Classroom (read-only) through a saved browser sign-in, as JSON.

    from classroom_parser import load_config, Reader, build_output

    cfg = load_config()
    with Reader(cfg) as r:
        data = build_output(r.collect_raw())
"""
__version__ = "0.1.0"

from .config import Config, load_config  # noqa: E402
from .scrape import NeedsLogin, Reader, build_output  # noqa: E402

__all__ = ["Config", "load_config", "Reader", "NeedsLogin", "build_output", "__version__"]
