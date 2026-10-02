"""One error contract for every API failure.

    {"error": {"code": "...", "message": "...", "field": null}}

Domain errors carry their own code; the HTTP status is chosen here, so business modules
never know about HTTP. Unexpected failures are logged and reported without a stack trace.
"""
import logging
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from repairshop.domain import (RuleError, AuthenticationRequired, PermissionDenied, NotFound,
                               VersionConflict, InvalidAction)

log = logging.getLogger('repairshop.api')

STATUS = [(AuthenticationRequired, 401), (PermissionDenied, 403), (NotFound, 404),
          (VersionConflict, 409), (InvalidAction, 409), (RuleError, 400)]


class ApiError(Exception):
    """An error raised by the HTTP layer itself rather than by a business rule."""

    def __init__(self, status, code, message, field=None, **extra):
        super().__init__(message)
        self.status, self.code, self.message, self.field, self.extra = status, code, message, field, extra


def body(code, message, field=None, **extra):
    return {'error': dict(code=code, message=message, field=field, **extra)}


def install(app):
    @app.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError):
        return JSONResponse(body(exc.code, exc.message, exc.field, **exc.extra), status_code=exc.status)

    @app.exception_handler(RuleError)
    async def rule_error(request: Request, exc: RuleError):
        status = next(code for kind, code in STATUS if isinstance(exc, kind))
        extra = {'refresh': True} if isinstance(exc, (VersionConflict, InvalidAction)) else {}
        return JSONResponse(body(exc.code, str(exc), **extra), status_code=status)

    @app.exception_handler(RequestValidationError)
    async def validation(request: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        location = [str(x) for x in first.get('loc', ()) if x not in ('body', 'query', 'path')]
        message = first.get('msg', 'Invalid request.')
        return JSONResponse(body('VALIDATION_ERROR', ('.'.join(location) + ': ' if location else '') + message,
                                 '.'.join(location) or None), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        codes = {404: 'NOT_FOUND', 405: 'METHOD_NOT_ALLOWED', 401: 'AUTHENTICATION_REQUIRED', 403: 'PERMISSION_DENIED'}
        return JSONResponse(body(codes.get(exc.status_code, 'HTTP_ERROR'), str(exc.detail)), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception):
        log.exception('Unhandled error on %s %s', request.method, request.url.path)
        return JSONResponse(body('INTERNAL_ERROR', 'Something went wrong. The details were written to the technical log.'),
                            status_code=500)
