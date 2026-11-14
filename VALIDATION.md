# Validation record

Run date: 14 November 2026. Environment: Python 3.12, Linux.

## Executed

- `python -m unittest discover -s tests -v`: **5 tests passed**.
- Browser JavaScript passes `node --check`.
- API integration checks use FastAPI TestClient and temporary SQLite databases.

## Not executed or not implemented

- No interactive browser run on the user's laptop or production deployment has been completed.
- No live OpenAI request was made. The Responses API adapter was checked with mocked responses only.
- No email, CRM or n8n integration is included.

CI workflow is included for Python 3.11 and 3.12. Inclusion of the workflow is not itself evidence that a GitHub-hosted run succeeded.
