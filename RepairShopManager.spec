from PyInstaller.utils.hooks import collect_data_files, collect_submodules
from pathlib import Path
a = Analysis(['launch.py'], pathex=[], binaries=[], datas=collect_data_files('tzdata'), hiddenimports=collect_submodules('keyring.backends') + ['sqlalchemy.dialects.sqlite'], hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=['tkinter'], noarchive=False)
# Qt 6.11 uses the Windows ICU ABI. A development PATH can contain a different
# ICU build (e.g. Poppler) with version-suffixed exports. Never bundle that copy.
a.binaries = [entry for entry in a.binaries if Path(entry[0]).name.lower() not in {'icuuc.dll', 'icudt78.dll'}]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='RepairShopManager', debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=False, disable_windowed_traceback=False)
