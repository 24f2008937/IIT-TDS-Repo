from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from datetime import datetime, timezone
import time
import uuid

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

START_TIME = time.time()
REQUEST_COUNT = 0
LOGS = []
EMAIL = "24f2008937@ds.study.iitm.ac.in"

@app.middleware("http")
async def track_requests(request: Request, call_next):
    global REQUEST_COUNT
    REQUEST_COUNT += 1
    req_id = str(uuid.uuid4())
    log_entry = {
        "level": "INFO",
        "ts": datetime.now(timezone.utc).isoformat(),
        "path": request.url.path,
        "request_id": req_id,
    }
    LOGS.append(log_entry)
    response = await call_next(request)
    response.headers["X-Request-ID"] = req_id
    return response

@app.get("/")
def root():
    return {"status": "ok", "email": EMAIL, "service": "observability"}

@app.get("/work")
def do_work(n: int = 1):
    _ = sum(i * i for i in range(max(0, n)))
    return {"email": EMAIL, "done": n}

@app.get("/metrics")
def get_metrics():
    content = (
        f"# HELP http_requests_total Total number of HTTP requests\n"
        f"# TYPE http_requests_total counter\n"
        f"http_requests_total {REQUEST_COUNT}\n"
    )
    return PlainTextResponse(content, media_type="text/plain; version=0.0.4; charset=utf-8")

@app.get("/healthz")
def healthz():
    return {"status": "ok", "uptime_s": max(0.0, time.time() - START_TIME)}

@app.get("/logs/tail")
def logs_tail(limit: int = 10):
    return LOGS[-limit:] if limit > 0 else LOGS
