"""Test support for the Rapid Response Network engine suite.

Importing this module makes `test_rapid_response_network.py` runnable in two
environments WITHOUT changing the production code or any other test:

  * On a normally provisioned machine (fastapi / pymongo / pydantic / redis
    installed) nothing is stubbed — the real modules are used, and these tests
    exercise the real dispatch/responder engine against its in-memory fallback.
  * In an offline/CI sandbox missing the web+DB layer, the few imports the pure
    engine transitively needs are shimmed so the engine logic can still be
    verified. A stub is installed ONLY when the real dependency is absent.

This module is intentionally NOT named conftest.py so it has zero effect on the
rest of HAVEN's test suite; only the file that imports it is affected.
"""
import os
import sys
import types

# Make `import services...` resolve regardless of the caller's CWD.
_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

# NOTE: this module used to call os.environ.setdefault("MONGO_ENDPOINT", "") here.
# services/db.py captures MONGO_ENDPOINT at IMPORT time, so that process-wide write
# permanently disabled the Mongo handles for every test module collected after it
# (admin stats "Database not connected", 503s on live-DB tests). The RRN engine
# tests do not need it: dispatch_service / responder_service use their own in-memory
# stores when no DB is configured. Do not mutate process-global DB configuration here.


def _missing(name):
    try:
        __import__(name)
        return False
    except Exception:
        return True


def install_stubs():
    if _missing("fastapi"):
        fa = types.ModuleType("fastapi")

        class HTTPException(Exception):
            def __init__(self, status_code=400, detail=""):
                super().__init__(detail)
                self.status_code = status_code
                self.detail = detail

        class _Status:
            HTTP_200_OK = 200
            HTTP_201_CREATED = 201
            HTTP_400_BAD_REQUEST = 400
            HTTP_401_UNAUTHORIZED = 401
            HTTP_403_FORBIDDEN = 403
            HTTP_404_NOT_FOUND = 404
            HTTP_409_CONFLICT = 409
            HTTP_422_UNPROCESSABLE_ENTITY = 422
            HTTP_429_TOO_MANY_REQUESTS = 429

        def _passthrough(default=None, **kw):
            return default

        class Request:  # pragma: no cover
            pass

        class WebSocket:  # pragma: no cover
            pass

        class APIRouter:
            def __init__(self, *a, **k):
                pass

            def _deco(self, *a, **k):
                return lambda fn: fn

            get = post = put = delete = patch = websocket = _deco

        fa.HTTPException = HTTPException
        fa.status = _Status()
        fa.Header = fa.Depends = fa.Body = fa.Path = fa.Query = _passthrough
        fa.Request = Request
        fa.WebSocket = WebSocket
        fa.APIRouter = APIRouter
        sys.modules["fastapi"] = fa

    if _missing("pydantic"):
        pd = types.ModuleType("pydantic")

        class BaseModel:
            def __init__(self, **data):
                for k, v in data.items():
                    setattr(self, k, v)

        pd.BaseModel = BaseModel
        pd.Field = lambda default=None, **kw: default
        sys.modules["pydantic"] = pd

    if _missing("pymongo"):
        pm = types.ModuleType("pymongo")

        class ReturnDocument:
            BEFORE = False
            AFTER = True

        class MongoClient:  # pragma: no cover
            def __init__(self, *a, **k):
                pass

            def __getitem__(self, _):
                return None

        errors = types.ModuleType("pymongo.errors")
        errors.PyMongoError = type("PyMongoError", (Exception,), {})
        errors.DuplicateKeyError = type("DuplicateKeyError", (errors.PyMongoError,), {})
        pm.ReturnDocument = ReturnDocument
        pm.MongoClient = MongoClient
        pm.errors = errors
        sys.modules["pymongo"] = pm
        sys.modules["pymongo.errors"] = errors

    if _missing("redis"):
        rd = types.ModuleType("redis")

        class Redis:  # pragma: no cover
            @classmethod
            def from_url(cls, *a, **k):
                raise RuntimeError("no redis in sandbox")

        rd.Redis = Redis
        rd.exceptions = types.ModuleType("redis.exceptions")
        sys.modules["redis"] = rd
        sys.modules["redis.exceptions"] = rd.exceptions


install_stubs()
