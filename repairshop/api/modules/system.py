"""Health, first-run setup, sign-in and sign-out."""
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from repairshop.domain import RuleError, timezone_name
from repairshop.permissions import granted
from repairshop.persistence import SCHEMA_VERSION
from repairshop.readmodels import needs_setup, schema_version
from repairshop.services import Service
from ..deps import runtime, service
from ..errors import ApiError
from ..schemas import Model, Ok
from ..sessions import COOKIE

router = APIRouter(tags=['system'])


class Health(BaseModel):
    status: str
    database: str
    schema_version: int = Field(serialization_alias='schema')
    expected_schema: int
    version: str


class Me(Model):
    id: int
    username: str
    name: str
    role: str
    permissions: list[str]
    shop_name: str
    timezone: str
    messaging_mode: str


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


class Setup(BaseModel):
    shop: str = Field(min_length=1, max_length=120)
    name: str = Field('Owner', min_length=1, max_length=120)
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=10, max_length=200)


class Status(BaseModel):
    setup_required: bool
    shop_name: str
    authenticated: bool


@router.get('/health', response_model=Health, response_model_by_alias=True)
def health(rt=Depends(runtime)):
    """Startup check for the launcher. Reveals no paths or credentials."""
    try:
        version = schema_version(rt.db)
        database = 'ok' if version == SCHEMA_VERSION else 'schema mismatch'
    except Exception:
        version, database = 0, 'unavailable'
    from ..app import _version
    return Health(status='ok' if database == 'ok' else 'degraded', database=database,
                  schema_version=version, expected_schema=SCHEMA_VERSION, version=_version())


@router.get('/auth/status', response_model=Status)
def status(request: Request, rt=Depends(runtime)):
    setup_required = needs_setup(rt.db)
    return Status(setup_required=setup_required, shop_name=rt.db.setting('shop_name', '') or '',
                  authenticated=bool(rt.sessions.user_id(request.cookies.get(COOKIE))))


def _me(s):
    u = s.user
    return Me(id=u['id'], username=u['username'], name=u['name'], role=u['role'],
              permissions=sorted(granted(u['role'])), shop_name=s.db.setting('shop_name', '') or '',
              timezone=timezone_name(), messaging_mode=s.db.setting('messaging_mode', 'test'))


def _start(rt, response, s):
    token = rt.sessions.create(s.user['id'])
    response.set_cookie(COOKIE, token, httponly=True, samesite='strict', secure=rt.config.secure_cookies,
                        path='/', max_age=rt.config.session_idle_seconds)
    return _me(s)


@router.post('/auth/setup', response_model=Me)
def setup(values: Setup, response: Response, rt=Depends(runtime)):
    if not needs_setup(rt.db):
        raise ApiError(409, 'SETUP_DONE', 'First-run setup has already been completed. Sign in instead.')
    s = Service(rt.db)
    s.setup(values.shop, values.username, values.password, name=values.name)
    return _start(rt, response, s)


@router.post('/auth/login', response_model=Me)
def login(values: Credentials, response: Response, rt=Depends(runtime)):
    s = Service(rt.db)
    try:
        s.login(values.username, values.password)
    except RuleError:
        raise ApiError(401, 'INVALID_CREDENTIALS', 'Incorrect username or password.')
    return _start(rt, response, s)


@router.post('/auth/logout', response_model=Ok)
def logout(request: Request, response: Response, rt=Depends(runtime)):
    rt.sessions.end(request.cookies.get(COOKIE))
    response.delete_cookie(COOKIE, path='/')
    return Ok()


@router.get('/auth/me', response_model=Me)
def me(s=Depends(service)):
    return _me(s)


@router.post('/system/shutdown', response_model=Ok)
def shutdown(s=Depends(service), rt=Depends(runtime)):
    """Close the local application. The browser tab is only a window onto this process."""
    if rt.server is None:
        raise ApiError(409, 'NOT_MANAGED', 'This server was not started by the RepairShop launcher.')
    rt.server.should_exit = True
    return Ok()
