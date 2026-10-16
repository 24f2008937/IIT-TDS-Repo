import re
from fastapi.testclient import TestClient
from api.index import app, EMAIL

client = TestClient(app)

# 1. Test baseline metrics
r = client.get("/metrics")
assert r.status_code == 200
m = re.search(r"http_requests_total\s+([0-9.]+)", r.text)
assert m is not None
baseline = float(m.group(1))

# 2. Make 4 calls to /work?n=K
for k in [2, 5, 1, 3]:
    res = client.get(f"/work?n={k}")
    assert res.status_code == 200
    data = res.json()
    assert data["email"] == EMAIL
    assert data["done"] == k

# 3. Read counter again
r2 = client.get("/metrics")
assert r2.status_code == 200
m2 = re.search(r"http_requests_total\s+([0-9.]+)", r2.text)
assert m2 is not None
after = float(m2.group(1))
assert after - baseline >= 4, f"Expected increase of at least 4, got {after - baseline}"

# 4. Health check
h = client.get("/healthz")
assert h.status_code == 200
h_data = h.json()
assert h_data["status"] == "ok"
assert isinstance(h_data["uptime_s"], (int, float)) and h_data["uptime_s"] >= 0

# 5. Logs tail
logs_res = client.get("/logs/tail?limit=10")
assert logs_res.status_code == 200
logs = logs_res.json()
assert isinstance(logs, list) and len(logs) > 0
for entry in logs:
    for field in ["level", "ts", "path", "request_id"]:
        assert field in entry, f"Missing field {field} in entry {entry}"
assert any("/work" in entry["path"] for entry in logs), "Expected at least one log entry containing /work"

print("All self-checks passed! ✨")
