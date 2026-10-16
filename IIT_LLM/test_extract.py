# Small assert-based self check for /extract
from fastapi.testclient import TestClient
from api.index import app

client = TestClient(app)

def test_extract():
    # 1. Standard invoice
    r = client.post("/extract", json={"text": "Invoice from Acme-9921 Industries Ltd.\nTotal due: 1250.50 USD\nPayment due by 2026-07-22."})
    assert r.status_code == 200
    d = r.json()
    assert "acme-9921 industries ltd" in d["vendor"].lower()
    assert abs(d["amount"] - 1250.50) <= 0.01
    assert d["currency"] == "USD"
    assert "2026-07-22" in d["date"]

    # 2. Empty / garbage input does not return 500
    r_empty = client.post("/extract", json={"text": ""})
    assert r_empty.status_code in (200, 422)

    r_garbage = client.post("/extract", json={"text": "random garbage words"})
    assert r_garbage.status_code == 200
    assert r_garbage.json()["currency"] in ("USD", "EUR", "GBP")

    # 3. Malformed JSON returns 422
    r_bad = client.post("/extract", content="bad json", headers={"Content-Type": "application/json"})
    assert r_bad.status_code == 422

    print("OK: /extract self-check passed")

if __name__ == "__main__":
    test_extract()
