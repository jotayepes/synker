"""Download and cache the ludusavi manifest (with ETag revalidation)."""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from synker import __version__, paths
from synker.manifest.index import ManifestIndex

log = logging.getLogger(__name__)

CHECK_INTERVAL = 24 * 3600
MANIFEST_FILE = "manifest.yaml"
INDEX_FILE = "manifest-index.json.gz"
STATE_FILE = "manifest-state.json"


@dataclass
class UpdateResult:
    updated: bool
    checked: bool
    games: int
    error: str | None = None


def _dir() -> Path:
    return paths.cache_dir()


def _read_state() -> dict:
    try:
        return json.loads((_dir() / STATE_FILE).read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def _write_state(state: dict) -> None:
    _dir().mkdir(parents=True, exist_ok=True)
    (_dir() / STATE_FILE).write_text(json.dumps(state), "utf-8")


def index_path() -> Path:
    return _dir() / INDEX_FILE


def update(url: str, force: bool = False, timeout: float = 60) -> UpdateResult:
    """Download the manifest if it changed and rebuild the index."""
    state = _read_state()
    idx = index_path()
    if not force and idx.exists() and time.time() - state.get("checked", 0) < CHECK_INTERVAL:
        return UpdateResult(updated=False, checked=False, games=-1)

    headers = {"User-Agent": f"synker/{__version__}"}
    if state.get("etag") and state.get("url") == url and idx.exists() and not force:
        headers["If-None-Match"] = state["etag"]
    req = urllib.request.Request(url, headers=headers)
    target = _dir() / MANIFEST_FILE
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            _dir().mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(".part")
            with tmp.open("wb") as fh:
                while chunk := resp.read(1 << 16):
                    fh.write(chunk)
            tmp.replace(target)
            etag = resp.headers.get("ETag")
    except urllib.error.HTTPError as exc:
        if exc.code == 304:
            state["checked"] = time.time()
            _write_state(state)
            return UpdateResult(updated=False, checked=True, games=-1)
        return UpdateResult(updated=False, checked=True, games=-1, error=f"HTTP {exc.code}")
    except (urllib.error.URLError, OSError) as exc:
        return UpdateResult(updated=False, checked=True, games=-1, error=str(exc))

    index = ManifestIndex.from_yaml_file(target)
    index.save(idx)
    # The raw YAML is only needed to build the index.
    target.unlink(missing_ok=True)
    _write_state({"url": url, "etag": etag, "checked": time.time(), "updated": time.time()})
    log.info("manifest updated: %d games with save data", len(index))
    return UpdateResult(updated=True, checked=True, games=len(index))


def load_index(url: str | None = None, auto_update: bool = True) -> ManifestIndex:
    """Return the cached index, downloading it first if needed."""
    if url and auto_update:
        result = update(url)
        if result.error:
            log.warning("could not update manifest: %s", result.error)
    path = index_path()
    if not path.exists():
        return ManifestIndex({})
    try:
        return ManifestIndex.load(path)
    except (OSError, ValueError) as exc:
        log.warning("manifest index unreadable (%s); ignoring it", exc)
        return ManifestIndex({})
