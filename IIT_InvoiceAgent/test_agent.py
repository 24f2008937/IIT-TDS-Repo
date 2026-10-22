import asyncio
import os
import json
import uuid
import httpx
from main import app, init_db

async def run_tests():
    target_url = os.environ.get("TARGET_URL")
    if target_url:
        print(f"Running tests against LIVE endpoint: {target_url}")
        client_ctx = httpx.AsyncClient(base_url=target_url, timeout=30.0)
    else:
        init_db()
        transport = httpx.ASGITransport(app=app)
        client_ctx = httpx.AsyncClient(transport=transport, base_url="http://testserver")

    async with client_ctx as client:
        print("=== Test 1: Agent Card Discovery ===")
        res = await client.get("/.well-known/agent-card.json")
        assert res.status_code == 200, f"Expected 200, got {res.status_code}"
        assert res.headers["content-type"].startswith("application/a2a+json")
        assert res.headers.get("A2A-Version") == "1.0"
        card = res.json()
        assert card["name"] and card["description"] and card["version"]
        assert isinstance(card["capabilities"], dict)
        assert any(s["id"] == "invoice_action_agent" for s in card["skills"])
        assert "application/vnd.ga5.invoice-claim-batch+json" in card["defaultInputModes"]
        assert "application/vnd.ga5.invoice-action-proposals+json" in card["defaultOutputModes"]
        assert "application/vnd.ga5.invoice-action-receipts+json" in card["defaultOutputModes"]
        print("Test 1 passed! ✅")

        print("=== Test 2: Protocol Header & Auth Validation ===")
        # Missing auth -> 401 with WWW-Authenticate header
        res_no_auth = await client.post(
            "/a2a/message:send",
            headers={"Content-Type": "application/a2a+json"},
            content=json.dumps({"message": {"messageId": "1"}})
        )
        assert res_no_auth.status_code in [401, 403], f"Expected 401/403, got {res_no_auth.status_code}"
        assert "www-authenticate" in res_no_auth.headers
        assert res_no_auth.headers.get("A2A-Version") == "1.0"

        # Invalid A2A-Version -> 400
        headers_bad_ver = {"Authorization": "Bearer token1", "A2A-Version": "2.0", "Content-Type": "application/a2a+json"}
        res_bad_ver = await client.post("/a2a/message:send", headers=headers_bad_ver, content=json.dumps({"message": {"messageId": "1"}}))
        assert res_bad_ver.status_code == 400, f"Expected 400 for bad version, got {res_bad_ver.status_code}"
        assert res_bad_ver.headers.get("A2A-Version") == "1.0"

        # Media Type Rejection: Content-Type: application/json -> 415
        headers_bad_ct = {"Authorization": "Bearer token1", "A2A-Version": "1.0", "Content-Type": "application/json"}
        res_bad_ct = await client.post("/a2a/message:send", headers=headers_bad_ct, content=json.dumps({"message": {"messageId": "1"}}))
        assert res_bad_ct.status_code == 415, f"Expected 415 for application/json, got {res_bad_ct.status_code}"
        assert res_bad_ct.headers.get("A2A-Version") == "1.0"
        print("Test 2 passed! ✅ (Auth, A2A-Version, and Media Type Rejection verified)")

        print("=== Test 3: Initial Invoice Batch Send (Propose Phase) ===")
        test_run_id = uuid.uuid4().hex[:6]
        headers1 = {"Authorization": f"Bearer user_token_alpha_{test_run_id}", "A2A-Version": "1.0", "Content-Type": "application/a2a+json"}
        packages = [
            # 1. Settle invoice
            {
                "packageId": "pkg_01",
                "text": """[COVER-01] Cover sheet
[ARC-01] In 2024, Acme Corp settled invoice INV-OLD-01 [ARC-02].
Vendor: Globex Technologies Ltd.
Invoice Number: INV-2026-1001
Total: INR 45,000.00
Case Findings:
Three-way match verified against purchase order records [DOC-POL-101], warehouse receiving note [DOC-POL-102], and verification receipt [DOC-POL-103].
Verified not a duplicate and no discrepancy found; within autonomous authority. Approved for settlement."""
            },
            # 2. Reject duplicate
            {
                "packageId": "pkg_02",
                "text": """[COVER-02] Cover sheet
Vendor: Cyberdyne Systems
Invoice Number: INV-2026-1002
Total: USD 2,500.00
Case Findings:
Reconciliation was attempted against ledger [LED-1002] and bank statement [BNK-1002].
Audit report [AUD-1002] confirmed identical commercial invoice was already paid under prior transaction.
No hold requested."""
            },
            # 3. Open exception
            {
                "packageId": "pkg_03",
                "text": """[COVER-03] Cover sheet
Vendor: Initech Logistics
Invoice Number: INV-2026-1003
Total: EUR 12,000.00
Case Findings:
Inspection of receiving note [REC-1003] and packing slip [PAK-1003] revealed material discrepancy with purchase order [PO-1003].
Quantity delivered does not match invoiced items, requiring open exception workflow."""
            },
            # 4. Hold invoice
            {
                "packageId": "pkg_04",
                "text": """[COVER-04] Cover sheet
Vendor: Wayne Industries
Invoice Number: INV-2026-1004
Total: GBP 8,000.00
Case Findings:
Receiving note [RN-1004] and carrier manifest [MAN-1004] received.
Payment is on hold pending quality inspection and compliance certificate [CERT-1004].
Not a duplicate."""
            },
            # 5. Request approval
            {
                "packageId": "pkg_05",
                "text": """[COVER-05] Cover sheet
Vendor: Stark Industries
Invoice Number: INV-2026-1005
Total: INR 950,000.00
Case Findings:
PO record [PO-1005] and delivery slip [DEL-1005] match invoice line items.
However, authority check [AUTH-1005] notes the amount exceeds autonomous threshold, outside delegated authority.
Manager sign-off required."""
            }
        ]

        batch_msg = {
            "message": {
                "messageId": "msg_batch_001",
                "role": "ROLE_USER",
                "parts": [{
                    "mediaType": "application/vnd.ga5.invoice-claim-batch+json",
                    "data": {
                        "batchId": "batch_test_01",
                        "policyRevision": "2026-v1",
                        "packages": packages
                    }
                }]
            },
            "configuration": {
                "returnImmediately": False,
                "historyLength": 20
            }
        }

        res_send = await client.post("/a2a/message:send", headers=headers1, content=json.dumps(batch_msg))
        assert res_send.status_code == 200, f"Send failed: {res_send.text}"
        assert res_send.headers["content-type"].startswith("application/a2a+json")
        assert res_send.headers.get("A2A-Version") == "1.0"
        data = res_send.json()
        assert "task" in data
        task = data["task"]
        task_id = task["id"]
        context_id = task["contextId"]
        assert task["status"]["state"] == "TASK_STATE_INPUT_REQUIRED"
        assert len(task["history"]) == 1
        assert len(task["artifacts"]) == 1

        proposals = task["artifacts"][0]["parts"][0]["data"]["proposals"]
        assert len(proposals) == 5

        expected_actions = ["settle_invoice", "reject_duplicate", "open_exception", "hold_invoice", "request_approval"]
        for idx, prop in enumerate(proposals):
            assert prop["action"] == expected_actions[idx], f"Expected {expected_actions[idx]}, got {prop['action']}"
            assert len(prop["actionId"]) >= 12
            assert prop["facts"]["vendorName"]
            assert prop["facts"]["invoiceNumber"]
            assert isinstance(prop["facts"]["amountMinor"], int)
            assert prop["facts"]["amountMinor"] > 0
            assert prop["facts"]["currency"] in ["INR", "USD", "EUR", "GBP"]
            assert len(prop["evidenceRefs"]) == 3
            assert not any("COVER" in r or "ARC" in r for r in prop["evidenceRefs"]), f"Excluded ref found: {prop['evidenceRefs']}"
            assert 60 <= len(prop["rationale"]) <= 1500
            assert prop["action"] in prop["rationale"]
        print("Test 3 passed! ✅ (All 5 distinct actions matched and verified)")

        print("=== Test 4: Idempotent Replay ===")
        # Re-send identical message
        res_replay = await client.post("/a2a/message:send", headers=headers1, content=json.dumps(batch_msg))
        assert res_replay.status_code == 200
        assert res_replay.headers["content-type"].startswith("application/a2a+json")
        assert res_replay.json()["task"]["id"] == task_id
        print("Test 4 passed! ✅")

        print("=== Test 5: Semantic Conflict on MessageId Re-use ===")
        altered_msg = dict(batch_msg)
        altered_msg["message"] = dict(batch_msg["message"])
        altered_msg["message"]["parts"] = [{
            "mediaType": "application/vnd.ga5.invoice-claim-batch+json",
            "data": {"batchId": "different_batch", "packages": []}
        }]
        res_conflict = await client.post("/a2a/message:send", headers=headers1, content=json.dumps(altered_msg))
        assert res_conflict.status_code == 409, f"Expected 409 for conflict, got {res_conflict.status_code}"
        assert res_conflict.headers["content-type"].startswith("application/a2a+json")
        assert res_conflict.headers.get("A2A-Version") == "1.0"
        assert res_conflict.json().get("error") == "IDEMPOTENCY_CONFLICT"
        print("Test 5 passed! ✅")

        print("=== Test 6: User Isolation ===")
        headers_outsider = {"Authorization": f"Bearer user_token_beta_{test_run_id}", "A2A-Version": "1.0", "Content-Type": "application/a2a+json"}
        # Outsider tries to read task_id
        res_out_get = await client.get(f"/a2a/tasks/{task_id}", headers=headers_outsider)
        assert res_out_get.status_code == 404, f"Expected 404 for outsider task access, got {res_out_get.status_code}"
        assert res_out_get.headers.get("A2A-Version") == "1.0"

        # Outsider tries to cancel task_id
        res_out_cancel = await client.post(f"/a2a/tasks/{task_id}:cancel", headers=headers_outsider)
        assert res_out_cancel.status_code == 404, f"Expected 404 for outsider cancel, got {res_out_cancel.status_code}"

        # Outsider lists tasks -> must be empty
        res_out_list = await client.get("/a2a/tasks", headers=headers_outsider)
        assert res_out_list.status_code == 200
        assert res_out_list.headers.get("A2A-Version") == "1.0"
        assert res_out_list.json()["tasks"] == []

        # Owner lists tasks -> contains task_id
        res_owner_list = await client.get("/a2a/tasks", headers=headers1)
        assert res_owner_list.status_code == 200
        assert any(t["id"] == task_id for t in res_owner_list.json()["tasks"])
        print("Test 6 passed! ✅")

        print("=== Test 7: Results Continuation & Execution ===")
        # Grader sends results: 4 ACCEPTED, 1 REJECTED
        results = []
        for idx, prop in enumerate(proposals):
            outcome = "ACCEPTED" if idx < 4 else "REJECTED"
            results.append({
                "packageId": prop["packageId"],
                "actionId": prop["actionId"],
                "action": prop["action"],
                "outcome": outcome,
                "receiptNonce": f"nonce_{uuid.uuid4().hex[:16]}"
            })

        cont_msg = {
            "message": {
                "messageId": "msg_cont_001",
                "taskId": task_id,
                "contextId": context_id,
                "role": "ROLE_USER",
                "parts": [{
                    "mediaType": "application/vnd.ga5.invoice-action-results+json",
                    "data": {
                        "batchId": "batch_test_01",
                        "results": results
                    }
                }]
            }
        }

        res_cont = await client.post("/a2a/message:send", headers=headers1, content=json.dumps(cont_msg))
        assert res_cont.status_code == 200, f"Continuation failed: {res_cont.text}"
        comp_task = res_cont.json()["task"]
        assert comp_task["status"]["state"] == "TASK_STATE_COMPLETED"
        assert len(comp_task["history"]) == 2
        assert len(comp_task["artifacts"]) == 2

        receipts_data = comp_task["artifacts"][1]["parts"][0]["data"]
        assert receipts_data["batchId"] == "batch_test_01"
        assert len(receipts_data["executions"]) == 4
        for exec_item in receipts_data["executions"]:
            assert "receiptNonce" in exec_item
            assert "packageId" in exec_item
            assert "action" in exec_item
            assert "facts" in exec_item
            assert "evidenceRefs" in exec_item
        print("Test 7 passed! ✅")

        print("=== Test 8: Terminal Task Cannot Be Cancelled (Returns 409) ===")
        res_post_cancel = await client.post(f"/a2a/tasks/{task_id}:cancel", headers=headers1)
        assert res_post_cancel.status_code == 409, f"Expected 409 for terminal task cancellation, got {res_post_cancel.status_code}"
        assert res_post_cancel.headers["content-type"].startswith("application/a2a+json")
        assert res_post_cancel.headers.get("A2A-Version") == "1.0"
        print("Test 8 passed! ✅")

        print("=== Test 9: Fresh Task Cancellation & Terminal Continuation Conflict ===")
        fresh_send = await client.post("/a2a/message:send", headers=headers1, content=json.dumps({
            "message": {
                "messageId": "msg_batch_cancel_test",
                "role": "ROLE_USER",
                "parts": [{
                    "mediaType": "application/vnd.ga5.invoice-claim-batch+json",
                    "data": {"batchId": "batch_cancel", "packages": [packages[0]]}
                }]
            }
        }))
        fresh_task_id = fresh_send.json()["task"]["id"]
        fresh_ctx = fresh_send.json()["task"]["contextId"]

        # Cancel while INPUT_REQUIRED
        cancel_res = await client.post(f"/a2a/tasks/{fresh_task_id}:cancel", headers=headers1)
        assert cancel_res.status_code == 200
        cancelled_task = cancel_res.json()
        assert cancelled_task["status"]["state"] == "TASK_STATE_CANCELLED"

        # Now attempt continuation on cancelled task -> must return 409
        bad_cont = await client.post("/a2a/message:send", headers=headers1, content=json.dumps({
            "message": {
                "messageId": "msg_cont_on_cancelled",
                "taskId": fresh_task_id,
                "contextId": fresh_ctx,
                "role": "ROLE_USER",
                "parts": [{
                    "mediaType": "application/vnd.ga5.invoice-action-results+json",
                    "data": {"batchId": "batch_cancel", "results": []}
                }]
            }
        }))
        assert bad_cont.status_code == 409
        assert bad_cont.headers["content-type"].startswith("application/a2a+json")
        print("Test 9 passed! ✅")

        print("=== Test 10: Race Condition: Concurrent Continuation vs Cancel ===")
        race_send = await client.post("/a2a/message:send", headers=headers1, content=json.dumps({
            "message": {
                "messageId": "msg_race_test",
                "role": "ROLE_USER",
                "parts": [{
                    "mediaType": "application/vnd.ga5.invoice-claim-batch+json",
                    "data": {"batchId": "batch_race", "packages": [packages[0]]}
                }]
            }
        }))
        race_task_id = race_send.json()["task"]["id"]
        race_ctx = race_send.json()["task"]["contextId"]
        race_prop = race_send.json()["task"]["artifacts"][0]["parts"][0]["data"]["proposals"][0]

        race_cont_req = client.post("/a2a/message:send", headers=headers1, content=json.dumps({
            "message": {
                "messageId": "msg_race_cont",
                "taskId": race_task_id,
                "contextId": race_ctx,
                "role": "ROLE_USER",
                "parts": [{
                    "mediaType": "application/vnd.ga5.invoice-action-results+json",
                    "data": {
                        "batchId": "batch_race",
                        "results": [{
                            "packageId": race_prop["packageId"],
                            "actionId": race_prop["actionId"],
                            "action": race_prop["action"],
                            "outcome": "ACCEPTED",
                            "receiptNonce": "race_nonce_123"
                        }]
                    }
                }]
            }
        }))
        race_cancel_req = client.post(f"/a2a/tasks/{race_task_id}:cancel", headers=headers1)

        # Execute both concurrently
        res_a, res_b = await asyncio.gather(race_cont_req, race_cancel_req)
        status_codes = sorted([res_a.status_code, res_b.status_code])
        assert status_codes == [200, 409], f"Expected exactly [200, 409], got {status_codes}"
        print("Test 10 passed! ✅ (Exactly one won with 200, the other got 409)")

        print("\nALL LOCAL TESTS PASSED 100%! 🚀🎉")

if __name__ == "__main__":
    asyncio.run(run_tests())
