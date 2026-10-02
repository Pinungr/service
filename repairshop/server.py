"""Run RepairShop Manager: one local backend process, opened in the default browser.

    RepairShopManager.exe / python -m repairshop  [--data-dir DIR] [--port N] [--no-browser]

Exactly one backend process serves one data folder. SQLite is the database and the
sessions and background loop live in this process, so a second worker must never be
started against the same data. A second launch finds the running instance through an
operating-system file lock (released automatically if the process dies, so a crash never
leaves a stale lock) and simply opens the browser on it.

The server listens on 127.0.0.1 only. Serving other computers on the network is a
deliberate future configuration, not a default.
"""
import argparse
import json
import logging
import os
import re
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOOPBACK = '127.0.0.1'
DEFAULT_PORT = 8765


class InstanceLock:
    """An exclusive OS lock on `server.lock` in the data folder."""

    def __init__(self, root):
        self.path = Path(root) / 'server.lock'
        self.handle = None

    def acquire(self):
        self.handle = open(self.path, 'a+b')
        try:
            if os.name == 'nt':
                import msvcrt
                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            self.handle.close()
            self.handle = None
            return False

    def release(self):
        if self.handle:
            try:
                if os.name == 'nt':
                    import msvcrt
                    self.handle.seek(0)
                    msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
            self.handle.close()
            self.handle = None


def free_port(preferred):
    """The preferred port when it is free on the loopback interface, otherwise any free one."""
    for port in (preferred, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind((LOOPBACK, port))
                return probe.getsockname()[1]
            except OSError:
                continue
    raise RuntimeError('No free local port is available.')


def healthy(port, timeout=1.0):
    try:
        with urllib.request.urlopen(f'http://{LOOPBACK}:{port}/api/health', timeout=timeout) as response:
            return json.loads(response.read()).get('status') in ('ok', 'degraded')
    except Exception:
        return False


def wait_until_healthy(port, seconds=30.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if healthy(port):
            return True
        time.sleep(0.2)
    return False


def configure_logging(root):
    handler = RotatingFileHandler(Path(root) / 'technical.log', maxBytes=2_000_000, backupCount=3, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s %(message)s'))
    logging.basicConfig(handlers=[handler], level=logging.WARNING, force=True)
    # The access log would record every URL, including repair and customer ids.
    logging.getLogger('uvicorn.access').disabled = True


def open_browser(port, enabled):
    url = f'http://{LOOPBACK}:{port}/'
    if enabled:
        webbrowser.open(url)
    return url


def main(argv=None):
    parser = argparse.ArgumentParser(description='RepairShop Manager (local web edition)')
    parser.add_argument('--data-dir', help='Shop data folder (default: %%LOCALAPPDATA%%\\RepairShopManager)')
    parser.add_argument('--port', type=int, default=DEFAULT_PORT)
    parser.add_argument('--no-browser', action='store_true', help='Start the server without opening a browser')
    parser.add_argument('--demo', action='store_true', help='Use the separate demonstration data folder')
    parser.add_argument('--smoke-test', action='store_true', help='Start, check the API and the web app respond, then stop')
    args = parser.parse_args(argv)
    # A windowed executable has no console; status lines must not crash it.
    for name in ('stdout', 'stderr'):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, 'w', encoding='utf-8'))
    from .api.config import Config, default_data_dir
    root = Path(args.data_dir) if args.data_dir else default_data_dir(args.demo)
    root.mkdir(parents=True, exist_ok=True)
    configure_logging(root)
    info = root / 'server.json'
    lock = InstanceLock(root)
    if not lock.acquire():
        # Already running for this data folder: bring the user to it instead of starting a second process.
        try:
            port = json.loads(info.read_text(encoding='utf-8'))['port']
        except Exception:
            port = None
        if port and wait_until_healthy(port, 15):
            print('RepairShop Manager is already running:', open_browser(port, not args.no_browser))
            return 0
        print('RepairShop Manager is already starting or not responding for this data folder.', file=sys.stderr)
        return 1
    try:
        import uvicorn
        from .api.app import create_app
        port = free_port(args.port)
        app = create_app(Config(data_dir=root, host=LOOPBACK, port=port))
        server = uvicorn.Server(uvicorn.Config(app, host=LOOPBACK, port=port, workers=1, log_config=None,
                                               access_log=False, lifespan='on'))
        app.state.runtime.server = server
        info.write_text(json.dumps({'port': port, 'pid': os.getpid()}), encoding='utf-8')
        worker = threading.Thread(target=server.run, name='repairshop-server', daemon=True)
        worker.start()
        if not wait_until_healthy(port):
            logging.error('The server did not become healthy on port %s', port)
            server.should_exit = True
            worker.join(10)
            return 1
        if args.smoke_test:
            with urllib.request.urlopen(f'http://{LOOPBACK}:{port}/', timeout=10) as page:
                html = page.read()
                script = re.search(rb'src="(/assets/[^\"]+\.js)"', html)
                ok = page.status == 200 and b'id="root"' in html and script is not None
            if ok:
                with urllib.request.urlopen(f'http://{LOOPBACK}:{port}{script.group(1).decode()}', timeout=10) as asset:
                    ok = asset.status == 200 and bool(asset.read(32))
            server.should_exit = True
            worker.join(15)
            return 0 if ok else 1
        print('RepairShop Manager is running at', open_browser(port, not args.no_browser))
        try:
            while worker.is_alive():
                worker.join(0.5)
        except KeyboardInterrupt:
            server.should_exit = True
            worker.join(15)
        return 0
    except Exception:
        logging.exception('RepairShop Manager could not start')
        raise
    finally:
        info.unlink(missing_ok=True)
        lock.release()


if __name__ == '__main__':
    raise SystemExit(main())
