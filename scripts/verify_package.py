"""Verify the actual extracted Windows package with development paths removed."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import uuid
import zipfile

root=Path(__file__).resolve().parents[1]
archive=root/'dist'/'RepairShopManager-Windows-x64.zip'
destination=root/'runtime'/('package-verification-'+uuid.uuid4().hex[:8])
destination.mkdir(parents=True)
with zipfile.ZipFile(archive) as z:
    bad=z.testzip()
    if bad:raise RuntimeError('Corrupt ZIP member: '+bad)
    members=z.namelist()
    if members != ['RepairShopManager.exe']:
        raise RuntimeError('The portable ZIP must contain exactly one application executable, with no source, documentation or separate runtime files.')
    z.extractall(destination)
package=destination
assert (package/'RepairShopManager.exe').read_bytes()[:2] == b'MZ'
environment=dict(os.environ)
environment['PATH']=str(Path(os.environ.get('SystemRoot','C:/Windows'))/'System32')
for name in ('PYTHONPATH','PYTHONHOME','QT_PLUGIN_PATH','QML2_IMPORT_PATH'):
    environment.pop(name,None)
startup=subprocess.STARTUPINFO()
startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW
startup.wShowWindow=0
times=[]
for _ in range(2):
    start=time.perf_counter()
    result=subprocess.run([str(package/'RepairShopManager.exe'),'--demo','--data-dir',str(root/'runtime'/'lifecycle-v12-demo'),'--smoke-test'],cwd=package,env=environment,startupinfo=startup,timeout=60)
    if result.returncode:raise RuntimeError(f'Packaged launch failed: {result.returncode}')
    times.append(round(time.perf_counter()-start,3))
output={'verified_at':datetime.now(timezone.utc).isoformat(),'archive':str(archive),'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'archive_bytes':archive.stat().st_size,'zip_integrity':'passed','archive_members':members,'packaging':'Single executable with embedded application bytecode and dependencies; no standalone source files','runtime_data_in_package':False,'launch_and_restart_exit_codes':[0,0],'launch_and_restart_seconds':times,'environment':'PATH contains only Windows System32; PYTHONPATH/PYTHONHOME/QT_PLUGIN_PATH removed','data':'Separate synthetic demo database','limitation':'Same Windows host; not a clean independent VM.'}
(root/'docs'/'package-verification.json').write_text(json.dumps(output,indent=2),encoding='utf-8')
print(json.dumps(output,indent=2))
