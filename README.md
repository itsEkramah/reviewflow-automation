# ReviewFlow Automation

A support-intake demonstration with structured triage, duplicate-aware requests and an explicit human review step. A FastAPI service stores tickets and decision events in SQLite; a plain JavaScript interface lets a reviewer edit, approve or reject drafts.

**Portfolio demonstration, not paid client work.** Built with AI assistance. The default provider is a deterministic keyword demo: it does not call an AI model. The optional OpenAI adapter is implemented and tested with mocked HTTP responses; a live provider run has not been completed. See [VALIDATION.md](VALIDATION.md).

## Run the free offline demo

Python 3.11+ is required.

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn reviewflow.app:app --host 127.0.0.1 --port 8001
```

Open <http://127.0.0.1:8001>. Create a draft from the synthetic message. Edit the draft, approve or reject it, and inspect the event log. **Approval only records a decision. Nothing is emailed, posted or written to a CRM.**

## The workflow

1. Validate a request ID and message.
2. Check for an existing request before calling the provider.
3. Produce a typed category, priority, summary and draft.
4. Queue the draft as `pending_review`.
5. Save a human-edited decision with optimistic version checking.
6. Append an audit event in the same database transaction.

The same request ID and message returns the existing ticket. Reusing an ID for different text returns `409 Conflict`. Two concurrent first requests can both reach the provider, but a unique database constraint prevents two stored tickets; the losing request receives a conflict. This is **not** a guarantee of exactly-once external API billing.

Approvals and rejections are final in this version. A stale version or an already reviewed ticket returns a conflict. The UI shows the latest 100 tickets; pagination and bulk operations are not implemented.

## Optional live AI mode

No key is needed for the default demo. To test live integration later, configure these variables **on your own machine**, using an API key and model available to your account:

```text
REVIEWFLOW_PROVIDER=openai
OPENAI_API_KEY=your-server-side-key
OPENAI_MODEL=your-supported-model-id
```

Restart the server after setting them. The app does not automatically load `.env` files. Do not place keys in source code, browser JavaScript, screenshots or GitHub. [`.env.example`](.env.example) contains variable names only.

Live mode sends the submitted message to the OpenAI Responses API, uses strict JSON Schema output, validates the returned object again with Pydantic, and sets `store=false`. That setting does not replace the provider's applicable data-retention policy. API use can incur charges; test only with synthetic messages until data-sharing requirements have been checked.

The adapter makes one request with a 30-second timeout. Refused, incomplete, malformed or failed responses are not queued. Retry manually; there is no silent fallback from live mode to fake AI output. Model output can still contain factual errors even when the schema is valid.

## API

```bash
curl -X POST http://127.0.0.1:8001/api/tickets \
  -H "Content-Type: application/json" \
  -d '{"request_id":"demo-001","message":"I was charged twice for invoice DEMO-42."}'
```

- `GET /api/tickets`: latest 100 tickets.
- `POST /api/tickets/{id}/decision`: `action`, `expected_version`, `reviewed_draft`.
- `GET /api/tickets/{id}/events`: ordered decision history.
- `/docs`: interactive API documentation.

## Checks and boundaries

Run `python -m unittest discover -s tests -v`. Checks cover replay behavior, conflicting request IDs, stale decisions, final review states, provider failure, request schemas and incomplete model responses. Tests use temporary databases and mocked provider responses; no paid network calls are made.

This app has no authentication, reviewer identity verification, role permissions, email sender, CRM connector, n8n integration or production deployment. Its event log records state changes, not a verified person. Bind to loopback and use synthetic data. Add those controls, a deletion/retention policy, monitoring, rate limits and deployment tests before considering real users. The application database contains the full submitted message and drafts.

Set `REVIEWFLOW_DB` to change the local database path. To reset the demonstration, stop the server and remove that database after preserving anything you need.

References: [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs), [Responses API](https://developers.openai.com/api/reference/resources/responses/methods/create), [FastAPI testing](https://fastapi.tiangolo.com/tutorial/testing/).
