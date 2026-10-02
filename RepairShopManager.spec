"""One-file Windows application: FastAPI backend and the built React UI."""
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

web = Path('frontend/dist').resolve()
if not (web / 'index.html').is_file() or not (web / 'assets').is_dir():
    raise RuntimeError('Build frontend assets first: npm run build in frontend/')

# Config.default_frontend_dist() looks beside repairshop.api when frozen.
web_files = [
    (str(source), str(Path('repairshop/api/static') / source.relative_to(web).parent))
    for source in web.rglob('*') if source.is_file()
]
a = Analysis(
    ['launch.py'],
    pathex=[],
    binaries=[],
    datas=collect_data_files('tzdata') + web_files,
    hiddenimports=collect_submodules('keyring.backends') + collect_submodules('uvicorn')
                  + ['sqlalchemy.dialects.sqlite'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'PyQt6', 'PySide6', 'legacy_desktop'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name='RepairShopManager', debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=False, disable_windowed_traceback=False,
)
