"""Атомарная запись JSON и file lock для state-файлов бота."""

from __future__ import annotations

import json
import logging
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger(__name__)


def atomic_write_json(path: Path, data: Any, *, indent: int = 2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=indent, sort_keys=True, ensure_ascii=False)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def read_json_file(path: Path, *, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        bak = path.with_suffix(path.suffix + ".bak")
        if bak.exists():
            try:
                logger.warning("JSON corrupt %s, trying backup: %s", path, exc)
                return json.loads(bak.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
        logger.error("JSON read failed %s: %s", path, exc)
        raise
    except OSError as exc:
        logger.error("JSON read failed %s: %s", path, exc)
        raise


@contextmanager
def file_lock(path: Path) -> Iterator[None]:
    """Эксклюзивная блокировка файла (fcntl на Linux)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        atomic_write_json(path, {})
    handle = open(path, "r+", encoding="utf-8")
    try:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except (ImportError, AttributeError, OSError) as exc:
            logger.warning("file_lock: fcntl unavailable for %s — lock disabled: %s", path, exc)
        yield
    finally:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except (ImportError, AttributeError, OSError):
            pass
        handle.close()


@contextmanager
def json_rw_lock(path: Path, *, default: Any) -> Iterator[Any]:
    """Read-modify-write под блокировкой с атомарной записью."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        atomic_write_json(path, default)
    with file_lock(path):
        try:
            data = read_json_file(path, default=default)
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("json_rw_lock: read failed %s — file not overwritten: %s", path, exc)
            raise
        if not isinstance(data, type(default)) and isinstance(default, dict):
            data = default.copy() if hasattr(default, "copy") else default
        yield data
        atomic_write_json(path, data)
        bak = path.with_suffix(path.suffix + ".bak")
        try:
            bak.write_text(
                json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            pass


__all__ = ["atomic_write_json", "read_json_file", "file_lock", "json_rw_lock"]
