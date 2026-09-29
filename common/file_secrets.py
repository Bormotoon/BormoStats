"""Load secrets from files (Docker/Kubernetes secrets) via the ``<NAME>_FILE`` convention.

``CH_PASSWORD_FILE=/run/secrets/ch_password`` sets ``CH_PASSWORD`` from the file content
unless ``CH_PASSWORD`` is already non-empty. This keeps secrets out of ``.env`` files,
process arguments and ``docker inspect`` output.
"""

from __future__ import annotations

import os
from collections.abc import MutableMapping
from pathlib import Path

SUFFIX = "_FILE"


def load_file_secrets(env: MutableMapping[str, str] | None = None) -> list[str]:
    """Populate ``env`` from ``*_FILE`` variables; returns the names that were set."""
    target = os.environ if env is None else env
    loaded: list[str] = []
    for key, path in list(target.items()):
        if not key.endswith(SUFFIX) or not path:
            continue
        name = key[: -len(SUFFIX)]
        if target.get(name):
            continue
        secret_path = Path(path)
        if not secret_path.is_file():
            raise RuntimeError(f"{key} points to a missing file: {path}")
        target[name] = secret_path.read_text(encoding="utf-8").strip()
        loaded.append(name)
    return loaded
