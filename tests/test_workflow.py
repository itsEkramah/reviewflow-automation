import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from reviewflow.app import create_app
from reviewflow.providers import ProviderError, demo_triage, openai_triage


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.calls = []
        def provider(message):
            self.calls.append(message)
            return demo_triage(message), "rules-demo"
        self.client = TestClient(create_app(Path(self.tmp.name) / "queue.db", provider=provider))

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()

    def test_replay_avoids_second_provider_call_and_conflicts(self):
        payload = {"request_id": "sample-1", "message": "I was charged twice."}
        one = self.client.post("/api/tickets", json=payload).json()
        two = self.client.post("/api/tickets", json=payload).json()
        self.assertEqual(one["id"], two["id"])
        self.assertTrue(two["replayed"])
        self.assertEqual(len(self.calls), 1)
        payload["message"] = "A different message"
        self.assertEqual(self.client.post("/api/tickets", json=payload).status_code, 409)

    def test_review_is_one_way_and_version_checked(self):
        row = self.client.post("/api/tickets", json={"request_id": "review-1", "message": "Login error, cannot access account."}).json()
        self.assertEqual(row["status"], "pending_review")
        payload = {"action": "approve", "expected_version": 9, "reviewed_draft": "Checked reply"}
        self.assertEqual(self.client.post(f'/api/tickets/{row["id"]}/decision', json=payload).status_code, 409)
        payload["expected_version"] = 1
        approved = self.client.post(f'/api/tickets/{row["id"]}/decision', json=payload)
        self.assertEqual(approved.json()["version"], 2)
        self.assertEqual(approved.json()["status"], "approved")
        self.assertEqual(self.client.post(f'/api/tickets/{row["id"]}/decision', json=payload).status_code, 409)
        events = self.client.get(f'/api/tickets/{row["id"]}/events').json()
        self.assertEqual([item["action"] for item in events], ["queued_for_review", "approved"])

    def test_provider_failure_does_not_queue(self):
        def bad_provider(message):
            raise ProviderError("Provider unavailable")
        client = TestClient(create_app(Path(self.tmp.name) / "bad.db", provider=bad_provider))
        self.assertEqual(client.post("/api/tickets", json={"request_id": "bad", "message": "Help me"}).status_code, 502)
        self.assertEqual(client.get("/api/tickets").json(), [])
        client.close()


class AdapterTests(unittest.TestCase):
    @patch.dict("os.environ", {"OPENAI_API_KEY": "test-only", "OPENAI_MODEL": "test-model"})
    def test_request_schema_and_output_validation(self):
        answer = demo_triage("Invoice question").model_dump_json()
        envelope = {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": answer}]}]}
        with patch("urllib.request.urlopen", return_value=io.StringIO(json.dumps(envelope))) as request:
            result = openai_triage("Invoice question")
        self.assertEqual(result.category, "billing")
        payload = json.loads(request.call_args.args[0].data)
        self.assertFalse(payload["store"])
        self.assertTrue(payload["text"]["format"]["strict"])
        self.assertFalse(payload["text"]["format"]["schema"]["additionalProperties"])

    @patch.dict("os.environ", {"OPENAI_API_KEY": "test-only", "OPENAI_MODEL": "test-model"})
    def test_refusal_or_incomplete_output_is_rejected(self):
        with patch("urllib.request.urlopen", return_value=io.StringIO('{"status":"incomplete","output":[]}')):
            with self.assertRaises(ProviderError):
                openai_triage("Question")


if __name__ == "__main__":
    unittest.main()
