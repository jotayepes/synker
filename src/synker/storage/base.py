"""Storage backend interface. Paths are always '/'-separated and relative to the backend root."""

from __future__ import annotations

import json
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, BinaryIO


class StorageError(Exception):
    pass


class Storage(ABC):
    name = "storage"

    @abstractmethod
    def describe(self) -> str: ...

    @abstractmethod
    def exists(self, path: str) -> bool: ...

    @abstractmethod
    def list(self, path: str) -> list[str]:
        """Names directly inside a folder ([] if it does not exist)."""

    @abstractmethod
    def open_read(self, path: str) -> BinaryIO: ...

    @abstractmethod
    def _write_stream(self, path: str, src: BinaryIO) -> None:
        """Write the whole stream to `path`, overwriting it atomically if possible."""

    @abstractmethod
    def delete(self, path: str) -> None: ...

    def close(self) -> None:  # noqa: B027 - optional hook
        pass

    # -- conveniences built on the primitives ----------------------------

    def read_bytes(self, path: str) -> bytes:
        with self.open_read(path) as fh:
            return fh.read()

    def write_bytes(self, path: str, data: bytes) -> None:
        import io

        self._write_stream(path, io.BytesIO(data))

    def upload(self, local: Path, path: str) -> None:
        with local.open("rb") as fh:
            self._write_stream(path, fh)

    def download(self, path: str, local: Path) -> None:
        local.parent.mkdir(parents=True, exist_ok=True)
        tmp = local.with_name(local.name + ".part")
        with self.open_read(path) as src, tmp.open("wb") as dst:
            while chunk := src.read(1 << 20):
                dst.write(chunk)
        tmp.replace(local)

    def read_json(self, path: str, default: Any = None) -> Any:
        if not self.exists(path):
            return default
        return json.loads(self.read_bytes(path).decode("utf-8"))

    def write_json(self, path: str, data: Any) -> None:
        self.write_bytes(path, json.dumps(data, indent=2, sort_keys=True).encode("utf-8"))

    def test(self) -> dict[str, Any]:
        """Check that we can write, read back and delete a file."""
        probe = f".synker-test-{uuid.uuid4().hex}"
        payload = b"synker storage test"
        self.write_bytes(probe, payload)
        try:
            if self.read_bytes(probe) != payload:
                raise StorageError("read-back mismatch")
        finally:
            self.delete(probe)
        return {"ok": True, "location": self.describe()}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
