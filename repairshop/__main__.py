import argparse
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys
from PyQt6.QtCore import QLockFile, QTimer
from PyQt6.QtWidgets import QApplication, QMessageBox
from .persistence import Database
from .services import Service
from .ui_widgets import Form, STYLE
from .ui import MainWindow


def main():
    parser = argparse.ArgumentParser(description="RepairShop Manager native desktop app")
    parser.add_argument("--data-dir")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--smoke-test", action="store_true", help="Launch UI briefly against an isolated selected database")
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    app.setApplicationName("RepairShop Manager")
    app.setOrganizationName("RepairShop")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    root = Path(args.data_dir or Path(os.environ.get("LOCALAPPDATA", Path.home())) / "RepairShopManager")
    if args.demo and not args.data_dir:
        root = root.parent / "RepairShopManager-Demo"
    root.mkdir(parents=True, exist_ok=True)
    log = RotatingFileHandler(root / "technical.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    logging.basicConfig(handlers=[log], level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    lock = QLockFile(str(root / "interactive.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        QMessageBox.warning(None, "Already open", "RepairShop Manager is already using this data folder. Return to its open window.")
        return 1
    try:
        db = Database(root)
        s = Service(db)
        if not db.one("SELECT id FROM users LIMIT 1"):
            d = Form("Welcome to RepairShop", description="Set up this shop and create its owner login. Data stays on this computer; no internet is required.")
            d.text("shop", "Shop name")
            d.text("name", "Owner's name")
            d.text("username", "Owner username")
            d.text("password", "Password (at least 10 characters)", password=True)
            if not d.submit(lambda v: s.setup(**v)):
                return 0
        else:
            d = Form("Welcome back", description=("Synthetic demonstration database" if args.demo else db.setting("shop_name", "Your shop")) + " · sign in to continue")
            d.text("username", "Username")
            d.text("password", "Password", password=True)
            if args.smoke_test and args.demo:
                s.login("demo", "DemoShop2026!")
            elif not d.submit(lambda v: s.login(**v)):
                return 0
        window = MainWindow(s, demo=args.demo)
        window.show()
        if args.smoke_test:
            QTimer.singleShot(1500, app.quit)
        result = app.exec()
        window.pool.waitForDone(30000)
        db.engine.dispose()
        return result
    except Exception as exc:
        QMessageBox.critical(None, "Startup needs attention", str(exc))
        return 1
    finally:
        lock.unlock()


if __name__ == "__main__":
    raise SystemExit(main())
