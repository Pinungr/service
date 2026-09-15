"""Consistent snapshots, checked archives and rollback-capable offline restore."""
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import tempfile
import uuid
import zipfile
from contextlib import closing
from .domain import now, RuleError
from .persistence import Database, SCHEMA_VERSION, insert
from . import __version__


def checksum(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot_archive(db, kind, destination):
    """Shared pre-migration and signed-in backup writer. Uses the actual snapshot schema."""
    from .local_files import managed_path
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / f"repairshop-{kind}-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}.zip"
    pending = target.with_suffix('.partial')
    try:
        with db.guard, tempfile.TemporaryDirectory(prefix='snapshot-', dir=db.root) as temp:
            snapshot = Path(temp) / 'shop.db'
            with db.read() as source, closing(sqlite3.connect(snapshot)) as dst:
                source.driver_connection.backup(dst)
                schema = dst.execute('PRAGMA user_version').fetchone()[0]
                refs = {r[0] for r in dst.execute('SELECT path FROM attachments')}
                if schema >= 5:
                    refs |= {r[0] for r in dst.execute('SELECT path FROM folder_files')}
            files = {'shop.db': snapshot}
            directories = set()
            # Include all customer files, including preserved edited summaries and recovery copies.
            customer_root = db.root / 'Customers'
            if customer_root.exists():
                for path in customer_root.rglob('*'):
                    if path.is_symlink() or path.is_junction():
                        raise RuleError('Customer folder contains an unsupported link: ' + str(path))
                    if path.is_file():
                        refs.add(path.relative_to(db.root).as_posix())
                    elif path.is_dir():
                        directories.add(path.relative_to(db.root).as_posix())
            for ref in refs:
                path = managed_path(db.root, ref)
                if not path.is_file():
                    raise RuleError('A referenced file is missing. Recover it before backing up: ' + ref)
                files[ref] = path
            manifest = dict(format=1, application=__version__, schema=schema, created=now(), kind=kind,
                credentials='Re-enter messaging secrets on a new computer.', directories=sorted(directories),
                files={name: dict(size=path.stat().st_size, sha256=checksum(path)) for name, path in files.items()})
            with zipfile.ZipFile(pending, 'w', zipfile.ZIP_DEFLATED) as archive:
                for name, path in files.items():
                    archive.write(path, name)
                archive.writestr('manifest.json', json.dumps(manifest, indent=2))
            Backups.validate(pending)
            os.replace(pending, target)
        return target
    finally:
        pending.unlink(missing_ok=True)


class Backups:
    def __init__(self, service):
        self.s, self.db = service, service.db

    def create(self, kind="daily", destination=None):
        self.s.require()
        if self.db.readonly:
            raise RuleError("Cannot run recovery backups from historical viewing.")
        destination = Path(destination or self.db.setting("backup_destination") or self.db.root / "backups")
        target = destination / "not-created"
        try:
            target = snapshot_archive(self.db, kind, destination)
            external_state = "not_configured"
            external = self.db.setting("external_backup")
            if external:
                ext = Path(external)
                if not ext.is_dir():
                    external_state = "pending_missing_drive"
                else:
                    try:
                        pending = ext / (target.name + ".partial")
                        shutil.copyfile(target, pending)
                        if checksum(pending) != checksum(target):
                            raise OSError("External copy checksum mismatch")
                        os.replace(pending, ext / target.name)
                        external_state = "verified"
                    except OSError:
                        external_state = "pending_copy_failed"
            with self.db.transaction() as c:
                insert(c, "backups", path=str(target), kind=kind, created=now(), state="verified", external_state=external_state)
                self.s.audit(c, "backup", None, "verified", {"path": str(target), "kind": kind, "external": external_state})
            if kind == "daily":
                self.retention(destination)
            return target
        except Exception as exc:
            with self.db.transaction() as c:
                insert(c, "backups", path=str(target), kind=kind, created=now(), state="failed", error=str(exc))
            raise

    def retention(self, destination):
        keep = max(1, int(self.db.setting("backup_retention", 30)))
        rows = self.db.rows("SELECT * FROM backups WHERE state='verified' AND kind='daily' ORDER BY id DESC")
        for row in rows[keep:]:
            path = Path(row["path"])
            if path.parent.resolve() == destination.resolve() and path.name.startswith("repairshop-daily-"):
                path.unlink(missing_ok=True)
                with self.db.transaction() as c:
                    c.execute("UPDATE backups SET state='retained_out' WHERE id=?", (row["id"],))

    @staticmethod
    def validate(archive_path, extract_to=None):
        with tempfile.TemporaryDirectory(prefix="repairshop-check-") as temp:
            target = Path(extract_to or temp)
            target.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(archive_path) as archive:
                names = archive.namelist()
                if len(names) != len(set(names)) or "manifest.json" not in names:
                    raise RuleError("Archive contains duplicate entries or no manifest.")
                if sum(info.file_size for info in archive.infolist()) > 20 * 1024**3:
                    raise RuleError("Archive exceeds the 20 GB safety limit.")
                for name in names:
                    p = PurePosixPath(name)
                    if p.is_absolute() or ".." in p.parts or p.as_posix() != name or any(part.rstrip(' .') != part for part in p.parts) or "\\" in name or ":" in name or not (name in ("manifest.json", "shop.db") or name.startswith(("managed/", "Customers/", "Internal/"))):
                        raise RuleError("Archive contains an unsafe path.")
                if len({name.casefold() for name in names}) != len(names):
                    raise RuleError('Archive paths collide on Windows.')
                manifest = json.loads(archive.read("manifest.json"))
                if manifest.get("format") != 1 or manifest.get("schema", 999) > SCHEMA_VERSION:
                    raise RuleError("Unsupported archive format or newer schema.")
                files = manifest.get("files", {})
                if set(names) != set(files) | {"manifest.json"} or "shop.db" not in files:
                    raise RuleError("Archive is incomplete or contains unlisted files.")
                for name, expected in files.items():
                    path = target / name
                    if not path.resolve().is_relative_to(target.resolve()):
                        raise RuleError('Archive extraction path escapes its destination.')
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(name) as src, path.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
                    if path.stat().st_size != expected["size"] or checksum(path) != expected["sha256"]:
                        raise RuleError("Archive checksum mismatch: " + name)
                from .local_files import managed_path
                for relative in manifest.get('directories', []):
                    directory = managed_path(target, relative)
                    directory.mkdir(parents=True, exist_ok=True)
            c = sqlite3.connect((target / "shop.db").as_uri() + "?mode=ro", uri=True)
            try:
                if c.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or c.execute("PRAGMA foreign_key_check").fetchall():
                    raise RuleError("Archived database failed integrity validation.")
                if c.execute("PRAGMA user_version").fetchone()[0] != manifest["schema"]:
                    raise RuleError("Archive schema does not match manifest.")
                refs = {r[0] for r in c.execute("SELECT path FROM attachments")}
                if manifest['schema'] >= 5:
                    refs |= {r[0] for r in c.execute('SELECT path FROM folder_files')}
                if not refs <= set(files):
                    raise RuleError("Archive is missing referenced attachments.")
                manifest["customers"] = c.execute("SELECT count(*) FROM customers").fetchone()[0]
                manifest["jobs"] = c.execute("SELECT count(*) FROM jobs").fetchone()[0]
            finally:
                c.close()
            return manifest

    def open_view(self, archive_path):
        self.s.require_permission('backup_restore')
        root = self.db.root / "archive-views" / uuid.uuid4().hex
        self.validate(archive_path, root)
        return Database(root, readonly=True)

    def restore(self, archive_path, confirmation):
        self.s.require_permission('backup_restore')
        if confirmation != "RESTORE":
            raise RuleError("Type RESTORE after reviewing the archive preview.")
        with self.db.guard:
            root = self.db.root
            recovery = root / ("restore-recovery-" + uuid.uuid4().hex)
            recovery.mkdir()
            staging = recovery / "candidate"
            self.validate(archive_path, staging)
            candidate = Database(staging)
            with candidate.transaction() as c:
                c.execute("INSERT INTO folder_queue(customer_id) SELECT id FROM customers WHERE 1 ON CONFLICT(customer_id) DO UPDATE SET revision=revision+1,error=''")
                c.execute("INSERT INTO settings VALUES ('notifications_paused','true') ON CONFLICT(key) DO UPDATE SET value='true'")
                c.execute("UPDATE outbox SET state='review_after_restore',error='Restored historical queue; review before re-enabling',updated=? WHERE state NOT IN ('delivered','read','cancelled')", (now(),))
            with candidate.read() as c:
                c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            candidate.engine.dispose()
            self.create("pre-restore")
            with self.db.read() as c:
                c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self.db.engine.dispose()
            old = recovery / "previous"
            old.mkdir()
            journal = root / 'restore-journal.json'
            from .local_files import publish
            original_names = [name for name in ('shop.db', 'shop.db-wal', 'shop.db-shm', 'managed', 'Customers', 'Internal') if (root / name).exists()]
            publish(journal, json.dumps({'recovery': recovery.name, 'started': now(), 'original_names': original_names}).encode('utf-8'))
            moved = []
            installed = []
            try:
                for name in ("shop.db", "shop.db-wal", "shop.db-shm", "managed", "Customers", "Internal"):
                    path = root / name
                    if path.exists():
                        os.replace(path, old / name)
                        moved.append(name)
                for name in ("shop.db", "managed", "Customers", "Internal"):
                    source = staging / name
                    if name in ("managed", "Customers", "Internal"):
                        source.mkdir(exist_ok=True)
                    os.replace(source, root / name)
                    installed.append(name)
            except Exception:
                for name in installed:
                    os.replace(root / name, staging / name)
                for name in moved:
                    os.replace(old / name, root / name)
                journal.unlink(missing_ok=True)
                raise
            journal.unlink()
            # Recovery directory deliberately retained; contains the previous full state.
            self.s.user = None
            return recovery

    def retry_external(self):
        self.s.require_permission('backup_restore')
        external = Path(self.db.setting('external_backup') or '')
        if not self.db.setting('external_backup') or not external.is_dir():
            raise RuleError('The configured external backup folder is still unavailable.')
        count = 0
        for row in self.db.rows("SELECT * FROM backups WHERE state='verified' AND external_state LIKE 'pending_%'"):
            source = Path(row['path'])
            if not source.is_file():
                continue
            pending = external / (source.name + '.partial')
            shutil.copyfile(source, pending)
            if checksum(source) != checksum(pending):
                raise RuleError('External copy checksum mismatch.')
            os.replace(pending, external / source.name)
            with self.db.transaction() as c:
                c.execute("UPDATE backups SET external_state='verified' WHERE id=?", (row['id'],))
            count += 1
        return count

    def due(self):
        self.s.require()
        results = []
        for kind, days in (("daily", 1), ("archive", int(self.db.setting("archive_days", 90)))):
            last = self.db.one("SELECT created FROM backups WHERE kind=? AND state='verified' ORDER BY id DESC LIMIT 1", (kind,))
            if not last or datetime.fromisoformat(last["created"]) + timedelta(days=days) <= datetime.now(timezone.utc):
                results.append(self.create(kind))
        return results
