"""Boundaries of the modular monolith, checked on every test run.

* The backend (`repairshop`, including its API) never imports PyQt and runs with PyQt absent.
* Domain and application modules never import the web framework.
* API route modules hold no SQL and make no HTTP calls to themselves.
* Nothing in the backend imports the legacy desktop presentation.
* The frontend never reaches the database or Python code directly.
"""
import ast
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKEND = ROOT / 'repairshop'
API = BACKEND / 'api'
FRONTEND = ROOT / 'frontend' / 'src'
WEB_FRAMEWORKS = ('fastapi', 'starlette', 'pydantic', 'uvicorn')


def python_files(folder):
    return sorted(p for p in folder.rglob('*.py') if '__pycache__' not in p.parts)


def imported_roots(path):
    """Every top-level module a file imports, including imports inside functions."""
    tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split('.')[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module.split('.')[0])
    return found


def test_backend_never_imports_pyqt_or_the_desktop_package():
    offenders = [str(p.relative_to(ROOT)) for p in python_files(BACKEND)
                 if imported_roots(p) & {'PyQt6', 'PyQt5', 'PySide6', 'legacy_desktop'}]
    assert offenders == []


def test_domain_and_application_modules_do_not_know_the_web_framework():
    offenders = [str(p.relative_to(ROOT)) for p in python_files(BACKEND)
                 # The executable entry point starts Uvicorn; it is delivery code,
                 # separate from the application and domain modules under review.
                 if API not in p.parents and p.name not in {'server.py', '__main__.py'}
                 and imported_roots(p) & set(WEB_FRAMEWORKS)]
    assert offenders == []


def test_api_route_modules_contain_no_sql_and_no_internal_http():
    sql = re.compile(r'\b(SELECT|INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|PRAGMA)\b')
    for path in python_files(API):
        text = path.read_text(encoding='utf-8')
        assert not sql.search(text), f'{path.name} contains SQL; move it to a service or read model'
        assert not imported_roots(path) & {'httpx', 'requests', 'urllib3', 'aiohttp'}, path.name


def test_the_backend_imports_and_serves_with_pyqt_absent(tmp_path):
    """Imports every backend module and answers a health request in a process where PyQt cannot load."""
    script = f'''
import sys, importlib, pkgutil
class Blocker:
    def find_spec(self, name, path, target=None):
        if name.split('.')[0] in ('PyQt6', 'PyQt5', 'PySide6'):
            raise ImportError('PyQt is not installed for the backend')
sys.meta_path.insert(0, Blocker())
import repairshop, repairshop.api
for module in pkgutil.walk_packages(repairshop.__path__, 'repairshop.'):
    if module.name != 'repairshop.__main__':
        importlib.import_module(module.name)
from fastapi.testclient import TestClient
from repairshop.api.app import create_app
from repairshop.api.config import Config
app = create_app(Config(data_dir=r"{tmp_path / 'shop'}", scheduler=False, frontend_dist=None))
with TestClient(app) as client:
    assert client.get('/api/health').json()['status'] == 'ok'
assert not [m for m in sys.modules if m.startswith(('PyQt6', 'legacy_desktop'))]
print('headless-ok')
'''
    result = subprocess.run([sys.executable, '-W', 'ignore', '-c', script], cwd=ROOT, capture_output=True, text=True, timeout=180)
    assert 'headless-ok' in result.stdout, result.stderr[-2000:]


def test_frontend_never_reaches_the_database_or_python():
    if not FRONTEND.is_dir():
        return
    # `/customers/42` is an API/browser route, not the managed Customers folder.
    forbidden = re.compile(r'sqlite|shop\.db|\.py["\']|LOCALAPPDATA|managed[/\\]|file://|(?<![A-Za-z0-9\\])[A-Za-z]:[/\\]', re.IGNORECASE)
    offenders = []
    for path in FRONTEND.rglob('*'):
        if path.suffix in ('.ts', '.tsx') and forbidden.search(path.read_text(encoding='utf-8')):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_frontend_calls_only_the_same_origin_api():
    if not FRONTEND.is_dir():
        return
    absolute = re.compile(r'https?://(?!www\.w3\.org)')
    offenders = [str(p.relative_to(ROOT)) for p in FRONTEND.rglob('*')
                 if p.suffix in ('.ts', '.tsx') and absolute.search(p.read_text(encoding='utf-8'))]
    assert offenders == []
