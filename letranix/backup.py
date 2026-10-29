"""Workspace backup and restore.

A backup is a zip holding a consistent SQLite snapshot (``sqlite3`` online
backup API) and the stored originals. Restore validates every archive member
name before extracting (no path traversal), takes a safety backup first, and
runs while the job and outbox workers are paused by the maintenance lock.
"""

import re
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from .db import audit

NAME = re.compile(r"^letranix-\d{8}-\d{6}(-\d+)?\.zip$")
MEMBER = re.compile(r"^(letranix\.db|documents/[a-f0-9]{32}|pages/[a-f0-9]{32}/[\w.-]{1,40}\.png)$")
MAX_UNCOMPRESSED = 4 * 1024**3


def _target(service) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = service.backups / f"letranix-{stamp}.zip"
    n = 1
    while path.exists():
        path = service.backups / f"letranix-{stamp}-{n}.zip"
        n += 1
    return path


def create(service, actor: str) -> dict:
    with service.db.maintenance:
        path = _target(service)
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = Path(tmp) / "letranix.db"
            src = sqlite3.connect(service.db.path)
            dst = sqlite3.connect(snapshot)
            try:
                src.backup(dst)
            finally:
                dst.close()
                src.close()
            partial = path.with_suffix(".partial")
            with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as z:
                z.write(snapshot, "letranix.db")
                for f in sorted(service.files.iterdir()):
                    if f.is_file() and re.fullmatch(r"[a-f0-9]{32}", f.name):
                        z.write(f, f"documents/{f.name}")
                for folder in sorted(service.page_dir.iterdir()):
                    if folder.is_dir() and re.fullmatch(r"[a-f0-9]{32}", folder.name):
                        for f in sorted(folder.glob("v*-p*.png")):
                            z.write(f, f"pages/{folder.name}/{f.name}")
            partial.replace(path)
        with service.db.connect() as c:
            audit(c, None, "backup.created", actor, {"backup": path.name, "bytes": path.stat().st_size})
    return describe(path)


def describe(path: Path) -> dict:
    return {"name": path.name, "bytes": path.stat().st_size,
            "created": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()}


def listing(service) -> list[dict]:
    return [describe(p) for p in sorted(service.backups.glob("letranix-*.zip"), reverse=True)
            if NAME.match(p.name)]


def resolve(service, name: str) -> Path:
    if not NAME.match(name):
        raise KeyError(name)
    path = service.backups / name
    if not path.is_file():
        raise KeyError(name)
    return path


def restore(service, name: str, actor: str) -> dict:
    path = resolve(service, name)
    with zipfile.ZipFile(path) as z:
        members = z.infolist()
        if not any(m.filename == "letranix.db" for m in members):
            raise ValueError("Backup does not contain a database")
        if any(not MEMBER.match(m.filename) or m.is_dir() for m in members):
            raise ValueError("Backup contains unexpected entries; refusing to restore")
        if sum(m.file_size for m in members) > MAX_UNCOMPRESSED:
            raise ValueError("Backup is too large")
        safety = create(service, actor)
        with service.db.maintenance, tempfile.TemporaryDirectory() as tmp:
            z.extractall(tmp)  # Member names validated above.
            restored = Path(tmp) / "letranix.db"
            check = sqlite3.connect(restored)
            try:
                if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("Backup database failed its integrity check")
                live = sqlite3.connect(service.db.path)
                try:
                    check.backup(live)
                finally:
                    live.close()
            finally:
                check.close()
            for folder in (service.files, service.page_dir):
                shutil.rmtree(folder)
                folder.mkdir()
            for sub in ("documents", "pages"):
                source = Path(tmp) / sub
                if source.is_dir():
                    shutil.copytree(source, service.root / sub, dirs_exist_ok=True)
            service.db.migrate()  # The backup may come from an older schema version.
            service.recover()
        with service.db.connect() as c:
            audit(c, None, "backup.restored", actor, {"backup": name, "safety_backup": safety["name"]})
    service.wakeup.set()
    return {"restored": name, "safety_backup": safety["name"]}
