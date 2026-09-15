"""Confined local paths and durable, unique file publication."""
import hashlib
import os
from pathlib import Path, PurePosixPath
import uuid
from .domain import RuleError


def managed_path(root, relative):
    root = Path(root).resolve()
    p = PurePosixPath(relative)
    # `Internal` holds shop-only copies that carry costs or margin, kept deliberately
    # outside `Customers` so a customer folder stays safe to hand over or export.
    if p.is_absolute() or '..' in p.parts or '\\' in relative or ':' in relative or not p.parts or p.parts[0] not in ('managed', 'Customers', 'Internal'):
        raise RuleError('Invalid managed file path.')
    path = root.joinpath(*p.parts)
    for part in (path, *path.parents):
        if part == root:
            break
        if part.is_symlink() or part.is_junction():
            raise RuleError('Managed folders cannot use symbolic links or junctions.')
    if not path.resolve().is_relative_to(root / p.parts[0]):
        raise RuleError('Managed file path escapes the data folder.')
    return path


def digest(data):
    return hashlib.sha256(data).hexdigest()


def publish(path, data, replace=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name('.saving-' + uuid.uuid4().hex)
    try:
        with pending.open('xb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(pending, path)
        else:
            # Windows rename fails if a destination already exists.
            os.rename(pending, path)
    finally:
        pending.unlink(missing_ok=True)
