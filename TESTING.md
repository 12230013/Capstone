# Automated testing

Run these commands from the repository root in PowerShell.

## Backend unit and API tests

The backend uses Python's built-in `unittest` runner and FastAPI's `TestClient`.
Use the backend virtual environment with the application's dependencies installed.

```powershell
.\backend\.venv\Scripts\python.exe -m unittest discover -s backend/tests -v
```

Run just the core unit tests or the chat/resource API tests with a filename pattern.

```powershell
.\backend\.venv\Scripts\python.exe -m unittest discover -s backend/tests -p "*units.py" -v
.\backend\.venv\Scripts\python.exe -m unittest discover -s backend/tests -p "test_api_*.py" -v
```

| File | Coverage |
| --- | --- |
| `backend/tests/test_units.py` | Message history cleanup, interleaved exchanges, password hashing, registration validation, phone-number validation, UTC timestamps |
| `backend/tests/test_cdr_units.py` | Communication counts, durations, contact aggregation, overnight and date filtering |
| `backend/tests/test_pipeline_structure.py` | Real router decisions, identifier context, RAG evidence branches, case filtering, text cleaning/chunking/loading |
| `backend/tests/test_integration_safety.py` | Refusal to delete application databases or test databases owned by another run |
| `backend/tests/test_api_chat.py` | Successful answers, model outages, timeouts, retry reuse, partial-write cleanup, conversation context, background titles |
| `backend/tests/test_api_resources.py` | Registration, folder operations, history responses, activity logs, original source documents |
| `backend/tests/test_api_investigation.py` | CDR summaries and filters, upstream service failures, relationship validation and missing citizens |
| `backend/tests/test_security_and_grounding.py` | Authentication on every investigation route, cookies, CSRF, expiry, logout, account ownership, missing information, verified citations |

API tests call the real FastAPI application through an in-process HTTP client.
MongoDB collections and model services are mocked, and file tests use temporary synthetic documents.
A running MongoDB service, Ollama, downloaded models, and real investigation documents are not required.
The fixtures use test accounts and do not write to your application's database.

The current Starlette version emits a deprecation warning about `httpx` in `TestClient`.
That warning does not indicate a test failure.
The simulated database-write error printed by one chat test is expected and checks rollback behavior.

## Frontend unit and API-client tests

Install the locked dependencies, then run Vitest.

```powershell
cd frontend
npm.cmd ci
npm.cmd test
```

For watch mode and a production build, use these commands from `frontend`.

```powershell
npm.cmd run test:watch
npm.cmd run build
```

| File | Coverage |
| --- | --- |
| `frontend/src/api.test.js` | Cookie credentials, CSRF, shared session checks, public login, expiry, cancellation, background polling |
| `frontend/src/components/AuthError.test.jsx` | Accessible error messages, focus, scrolling, validation formatting |
| `frontend/src/components/RequireSession.test.jsx` | Protected pages, loading state, expired sessions, backend outages and retry |
| `frontend/src/pages/Auth.test.jsx` | Sign-in failures and success, duplicate submission prevention, registration errors and redirect |
| `frontend/src/pages/Chat.test.jsx` | Failed-query recovery, retry deduplication, pending submissions, source-panel opening |
| `frontend/src/pages/SourcesPanel.test.jsx` | Original-document loading, cited sentence highlighting, missing-file fallback, close controls, cancellation |

Frontend tests render real React components in jsdom and simulate user interactions.
Network responses are mocked. The frontend API-client tests verify outgoing request options and session handling.
The suite uses one worker to keep memory usage modest on this laptop.

## Scope

The unit/API and component suites above check behavior with controlled dependencies.
The additional integration and browser suites below exercise real MongoDB persistence and browser rendering.
Live model answer quality, GPU compatibility, and production HTTPS infrastructure require separate checks.

## Integration tests with MongoDB

These tests exercise actual MongoDB persistence through the application's FastAPI endpoints.
Start the local MongoDB service, then run from the repository root.

```powershell
.\backend\.venv\Scripts\python.exe -m unittest discover -s backend/integration_tests -v
```

A unique `acc_test_...` database and temporary synthetic document are created for each run and removed on shutdown.
The application database defaults to `acc_database`; the integration process selects its own test database with `MONGO_DB_NAME`.
The test server refuses a database name outside the `acc_test_` prefix and refuses to reuse a nonempty test database.
Browser teardown also checks the run's ownership marker before removing its database.
Only the model/embedding services are replaced with controlled responses. Session handling, routes, grounding validation, file access, and database operations execute real application code.
The default integration MongoDB URI is `mongodb://127.0.0.1:27017`; use `TEST_MONGO_URI` to point to a dedicated test server.
If a test process is forcibly terminated, its generated database can remain and should be reviewed by its `acc_test_` name before cleanup.

## Structural testing with statement and branch coverage

Install the coverage tool once, then run from the repository root.

```powershell
.\backend\.venv\Scripts\python.exe -m pip install -r backend/requirements-test.txt
.\backend\.venv\Scripts\python.exe -m coverage run -m unittest discover -s backend/tests -q
.\backend\.venv\Scripts\python.exe -m coverage run --append -m unittest discover -s backend/integration_tests -q
.\backend\.venv\Scripts\python.exe -m coverage report
.\backend\.venv\Scripts\python.exe -m coverage html
.\backend\.venv\Scripts\python.exe -m coverage json
```

`.coveragerc` enables branch measurement for `backend/app`.
Generated HTML and JSON reports are written under `test-results/backend/` and include uncovered statements and branches.
Coverage measures executed code paths. It does not prove correctness or imply that every branch has been tested.
The aggregate includes the isolated unit/API suite and the real MongoDB integration suite.

## Browser integration and automated acceptance scenarios

Start MongoDB. Install the Chromium test browser once and run Playwright from `frontend`.

```powershell
cd frontend
npm.cmd exec -- playwright install chromium
npm.cmd run test:e2e
npm.cmd run test:e2e:report
```

Playwright starts a dedicated backend on port 8001 and a frontend on port 5181, using a disposable test database.
Both ports must be available. It does not reuse the normal application servers on ports 8000 and 5173.
The six scenarios exercise registration/login/logout, grounded answers and source documents, missing information, retry recovery, folder persistence and alignment, and account isolation.
The HTML report is under `frontend/playwright-report/`. Screenshots and failure traces are under `frontend/test-results/browser/`.
Screenshots are attached to the report for each acceptance scenario.
The model/embedding services use controlled synthetic responses; no live model inference is required.

Test data is in `tests/fixtures/acceptance.json`.
Manual acceptance criteria and a reviewer sign-off record are in [tests/UAT_CHECKLIST.md](tests/UAT_CHECKLIST.md).
Automated acceptance checks and actual end-user sign-off are recorded separately.

The latest executed results, measured coverage, resolved defects, and remaining gaps are recorded in [tests/TEST_RESULTS.md](tests/TEST_RESULTS.md).
