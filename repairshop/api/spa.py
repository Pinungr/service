"""Serve the built React application from the same origin as the API.

`/api/*` is API-only. Every other GET returns a real built file when one exists, and
otherwise `index.html`, so a refreshed or bookmarked client route such as
`/repairs/42` still opens the application.
"""
from pathlib import Path
from fastapi import Request
from fastapi.responses import FileResponse, HTMLResponse
from starlette.staticfiles import StaticFiles

NOT_BUILT = """<!doctype html><meta charset="utf-8"><title>RepairShop Manager</title>
<body style="font-family:system-ui;padding:40px;color:#102a43">
<h1>RepairShop Manager</h1><p>The web interface has not been built yet.</p>
<p>Run <code>npm run build</code> in <code>frontend/</code>, or use the Vite development server.</p></body>"""


def install(app, dist):
    dist = Path(dist).resolve() if dist else None
    if dist and (dist / 'assets').is_dir():
        app.mount('/assets', StaticFiles(directory=dist / 'assets'), name='assets')

    @app.get('/{path:path}', include_in_schema=False)
    async def spa(path: str, request: Request):
        if path == 'api' or path.startswith('api/'):
            from .errors import ApiError
            raise ApiError(404, 'NOT_FOUND', 'No such API endpoint.')
        if not dist or not (dist / 'index.html').is_file():
            return HTMLResponse(NOT_BUILT)
        candidate = (dist / path).resolve()
        # Only files inside the build folder are ever served.
        if path and candidate.is_file() and candidate.is_relative_to(dist):
            return FileResponse(candidate)
        return FileResponse(dist / 'index.html', headers={'Cache-Control': 'no-cache'})
