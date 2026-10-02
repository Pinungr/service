"""Runtime configuration for the single backend process."""
import os
from dataclasses import dataclass, field
from pathlib import Path


def default_data_dir(demo=False):
    root = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'RepairShopManager'
    return root.parent / 'RepairShopManager-Demo' if demo else root


def default_frontend_dist():
    """Built React assets: bundled beside the package when frozen, else the repo's frontend/dist."""
    here = Path(__file__).resolve().parent
    for candidate in (here / 'static', here.parents[1] / 'frontend' / 'dist'):
        if (candidate / 'index.html').is_file():
            return candidate
    return None


@dataclass
class Config:
    data_dir: Path
    host: str = '127.0.0.1'
    port: int = 8765
    frontend_dist: Path | None = field(default_factory=default_frontend_dist)
    #: Background notification, reminder, backup and folder work. Off in most tests.
    scheduler: bool = True
    scheduler_interval: float = 30.0
    #: Idle sessions expire; the shop counter is a shared computer.
    session_idle_seconds: int = 12 * 3600
    secure_cookies: bool = False
