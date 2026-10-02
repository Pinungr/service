"""Request-scoped access to the one database and the signed-in user's service."""
from fastapi import Depends, Request
from repairshop.domain import AuthenticationRequired, PermissionDenied
from repairshop.services import Service
from .sessions import COOKIE


def runtime(request: Request):
    return request.app.state.runtime


def service(request: Request) -> Service:
    """A Service bound to the signed-in user. Permissions are rechecked on every call."""
    rt = request.app.state.runtime
    user_id = rt.sessions.user_id(request.cookies.get(COOKIE))
    if not user_id:
        raise AuthenticationRequired('Please sign in.')
    s = Service(rt.db)
    s.resume(user_id)
    return s


def permission(*names):
    """Route dependency: a signed-in user holding every named permission."""
    def check(s: Service = Depends(service)):
        s.require_permission(*names)
        return s
    return check


def owner(s: Service = Depends(service)):
    if s.user['role'] != 'owner':
        raise PermissionDenied('Only the shop owner can do this.')
    return s
