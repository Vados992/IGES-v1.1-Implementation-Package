"""RFC 9457 errors with request tracing; no private payloads in diagnostics."""
import logging
import time
from uuid import uuid4

from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

log = logging.getLogger('iges.requests')


def problem(status, code, request_id=None, headers=None):
    return JSONResponse(status_code=status, media_type='application/problem+json', headers=headers,
                        content={'type': 'about:blank', 'title': code, 'status': status, 'detail': code,
                                 'instance': 'urn:uuid:' + (request_id or str(uuid4()))})


def install(app):
    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return problem(exc.status_code, str(exc.detail), getattr(request.state, 'trace_id', None), exc.headers)

    @app.exception_handler(RequestValidationError)
    async def invalid(request, exc):
        # Pydantic errors may contain originals, tokens, quotations and private text.
        return problem(422, 'REQUEST_VALIDATION_FAILED', getattr(request.state, 'trace_id', None))

    @app.exception_handler(IntegrityError)
    async def conflict(request, exc):
        return problem(409, 'DATABASE_CONSTRAINT_CONFLICT', getattr(request.state, 'trace_id', None))

    @app.exception_handler(SQLAlchemyError)
    async def database(request, exc):
        return problem(503, 'DATABASE_UNAVAILABLE', getattr(request.state, 'trace_id', None))

    @app.middleware('http')
    async def trace(request, call_next):
        request.state.trace_id = str(uuid4())
        started = time.monotonic()
        response = await call_next(request)
        response.headers['X-Request-ID'] = request.state.trace_id
        # Do not log paths (private UUIDs), query strings, bodies or identities.
        log.info('request_id=%s method=%s status=%s duration_ms=%.1f', request.state.trace_id,
                 request.method, response.status_code, (time.monotonic() - started) * 1000)
        return response
