from __future__ import annotations

import os
from pathlib import Path


def data_root() -> Path:
    return Path(os.environ.get("OPENRUSSIAN_DATA_DIR", "data")).expanduser().resolve()

