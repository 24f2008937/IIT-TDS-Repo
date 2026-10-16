import re
import time
import uuid
from collections import defaultdict, deque
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

ASSIGNED_ORIGIN = "https://app-in3lz1.example.com"
EMAIL = "24f2008937@ds.study.iitm.ac.in"
RATE_LIMIT_BUCKET = 15
RATE_LIMIT_WINDOW = 10.0  # seconds

# ponytail: in-memory deque per client ID is minimal and exact for single-instance service; upgrade to Redis if horizontally scaled
client_buckets: dict[str, deque[float]] = defaultdict(deque)


def is_allowed_origin(origin: str | None) -> bool:
    if not origin:
        return False
    origin = origin.rstrip("/")
    if origin == ASSIGNED_ORIGIN:
        return True
    if origin in (
        "https://exam.sanand.workers.dev",
        "https://tds-network-games.sanand.workers.dev",
        "https://tds.s-anand.net",
    ):
        return True
    if re.match(r"^https://[a-zA-Z0-9.-]+\.sanand\.workers\.dev$", origin):
        return True
    if re.match(r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$", origin):
        return True
    return False


def is_rate_limited(client_id: str) -> bool:
    now = time.monotonic()
    bucket = client_buckets[client_id]
    cutoff = now - RATE_LIMIT_WINDOW
    while bucket and bucket[0] <= cutoff:
        bucket.popleft()
    if len(bucket) >= RATE_LIMIT_BUCKET:
        return True
    bucket.append(now)
    return False


# --- Middleware 3: Per-Client Rate Limiting ---
class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # ponytail: skip rate limiting on preflight OPTIONS so browser CORS checks don't consume budget
        if request.method == "OPTIONS":
            return await call_next(request)
        client_id = (request.headers.get("x-client-id") or "").strip() or "anonymous"
        if is_rate_limited(client_id):
            req_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())
            return JSONResponse(
                status_code=429,
                content={"detail": "Too Many Requests", "request_id": req_id},
                headers={"Retry-After": "10", "X-Request-ID": req_id},
            )
        return await call_next(request)


# --- Middleware 1: Request Context Propagator ---
class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        inbound_id = (request.headers.get("x-request-id") or "").strip()
        req_id = inbound_id if inbound_id else str(uuid.uuid4())
        request.state.request_id = req_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = req_id
        return response


# --- Middleware 2: Scoped CORS ---
class ScopedCORSMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        origin = request.headers.get("origin")
        if request.method == "OPTIONS":
            if is_allowed_origin(origin):
                return Response(
                    status_code=200,
                    headers={
                        "Access-Control-Allow-Origin": origin,
                        "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS, HEAD",
                        "Access-Control-Allow-Headers": request.headers.get("access-control-request-headers", "*") or "*",
                        "Access-Control-Expose-Headers": "X-Request-ID, *",
                        "Access-Control-Max-Age": "86400",
                        "Vary": "Origin",
                    },
                )
            return Response(status_code=400, content="Disallowed CORS origin")

        response = await call_next(request)
        if origin and is_allowed_origin(origin):
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Expose-Headers"] = "X-Request-ID, *"
            response.headers["Vary"] = "Origin"
        return response


app = FastAPI(title="Middleware Stack Service")

# ponytail: registration order ensures ScopedCORS is outermost (handles preflight first and decorates all responses including 429),
# RequestContext is middle (ensures X-Request-ID is always populated), RateLimit is inner.
app.add_middleware(RateLimitMiddleware)
app.add_middleware(RequestContextMiddleware)
app.add_middleware(ScopedCORSMiddleware)


@app.get("/")
def root():
    return {"status": "ok", "service": "middleware-stack", "email": EMAIL}


@app.get("/ping")
async def ping(request: Request):
    return {
        "email": EMAIL,
        "request_id": getattr(request.state, "request_id", None),
    }


if __name__ == "__main__":
    from starlette.testclient import TestClient

    client = TestClient(app)

    # 1. Supplied X-Request-ID
    r1 = client.get(
        "/ping",
        headers={
            "X-Request-ID": "custom-req-id-12345",
            "X-Client-Id": "m-ctx1",
            "Origin": "https://exam.sanand.workers.dev",
        },
    )
    assert r1.status_code == 200, f"Expected 200, got {r1.status_code}"
    b1 = r1.json()
    assert b1["email"] == EMAIL
    assert b1["request_id"] == "custom-req-id-12345"
    assert r1.headers.get("x-request-id") == "custom-req-id-12345"
    assert r1.headers.get("access-control-allow-origin") == "https://exam.sanand.workers.dev"

    # 2. Fresh generated X-Request-ID
    r2 = client.get(
        "/ping",
        headers={
            "X-Client-Id": "m-ctx2",
            "Origin": ASSIGNED_ORIGIN,
        },
    )
    assert r2.status_code == 200
    b2 = r2.json()
    assert b2["email"] == EMAIL
    assert b2["request_id"] and b2["request_id"] != "custom-req-id-12345"
    assert r2.headers.get("x-request-id") == b2["request_id"]
    assert r2.headers.get("access-control-allow-origin") == ASSIGNED_ORIGIN

    # 3. Disallowed origin receives no ACAO header
    r_evil = client.get(
        "/ping",
        headers={
            "Origin": "https://evil.example.com",
            "X-Client-Id": "m-ctx3",
        },
    )
    assert r_evil.status_code == 200
    assert "access-control-allow-origin" not in r_evil.headers

    # 4. Preflight OPTIONS
    r_opt_ok = client.options(
        "/ping",
        headers={
            "Origin": ASSIGNED_ORIGIN,
            "Access-Control-Request-Method": "GET",
        },
    )
    assert r_opt_ok.status_code == 200
    assert r_opt_ok.headers.get("access-control-allow-origin") == ASSIGNED_ORIGIN

    r_opt_bad = client.options(
        "/ping",
        headers={
            "Origin": "https://unauthorized-origin.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert r_opt_bad.status_code == 400
    assert "access-control-allow-origin" not in r_opt_bad.headers

    # 5. Rate limiting: 15 succeed, 16th gets 429
    flood_id = "test-flood-client"
    for i in range(15):
        rf = client.get(
            "/ping",
            headers={"X-Client-Id": flood_id, "Origin": ASSIGNED_ORIGIN},
        )
        assert rf.status_code == 200, f"Call {i+1} failed"

    rf_blocked = client.get(
        "/ping",
        headers={"X-Client-Id": flood_id, "Origin": ASSIGNED_ORIGIN},
    )
    assert rf_blocked.status_code == 429
    assert rf_blocked.headers.get("access-control-allow-origin") == ASSIGNED_ORIGIN
    assert "x-request-id" in rf_blocked.headers
    assert rf_blocked.json()["request_id"] == rf_blocked.headers.get("x-request-id")

    # 6. Fresh client succeeds immediately
    rf_fresh = client.get(
        "/ping",
        headers={"X-Client-Id": "fresh-client-id", "Origin": ASSIGNED_ORIGIN},
    )
    assert rf_fresh.status_code == 200

    print("All unit assertions passed successfully!")
