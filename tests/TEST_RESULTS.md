# Testing results

Date: 13 November 2026 (Asia/Thimphu)

## Execution summary

| Suite | Executed cases | Passed | Failed |
| --- | ---: | ---: | ---: |
| Backend unit/API and structural branch tests | 87 | 87 | 0 |
| Frontend unit/component/API-client tests | 30 | 30 | 0 |
| Backend API-to-MongoDB integration workflows | 6 | 6 | 0 |
| Chromium browser integration and automated acceptance scenarios | 6 | 6 | 0 |
| Total automated cases | 129 | 129 | 0 |

The frontend production build also passed.

## Requested testing categories

| Requirement | Work performed | Evidence / status |
| --- | --- | --- |
| Test cases and test data | Named test methods, explicit expected outcomes, normal/boundary/error inputs, and shared synthetic acceptance fixtures | `tests/fixtures/acceptance.json` and the test files listed in `TESTING.md` |
| Unit testing | Input validation, password hashing, history processing, analytics, document processing, routing, retrieval, grounding, session/client behavior, and component interactions | Backend and frontend suites passed |
| Backend structural testing | Execution of decision/error branches with statement and branch measurement | Coverage generated; partial coverage, with uncovered paths recorded below |
| Backend functional testing | HTTP requests against the real FastAPI routing and validation layer | Positive, invalid-input, authentication, ownership, timeout, missing-data, and retry cases passed |
| Integration testing | API-to-MongoDB workflows plus real browser-to-React-to-FastAPI-to-MongoDB requests | Six database workflows and six browser scenarios passed |
| User acceptance testing | Acceptance criteria, browser scenarios, screenshots, and a human review record | Automated scenarios passed; actual end-user approval and live-model review remain pending |

## Test environment and data

- Backend unit/API tests use controlled database/model fixtures.
- Integration tests use actual local MongoDB with a uniquely named `acc_test_...` database.
- Browser tests use the real React frontend on port 5181 and the real FastAPI routes on port 8001.
- Temporary source files contain only the synthetic statement from `fixtures/acceptance.json`.
- The account fixture uses synthetic users and a different generated email/employee ID for each scenario.
- The model/embedding boundary is controlled for reproducibility. The real grounding validator still processes the model-shaped results.
- Database cleanup requires the disposable prefix and this run's ownership marker. Cleanup safety has four dedicated regression tests.

## Structural coverage

Scope: production Python files under `backend/app`. Results combine the unit/API suite and the real MongoDB integration suite.

| Measure | Covered | Total | Percentage |
| --- | ---: | ---: | ---: |
| Statements | 1,204 | 2,783 | 43.26% |
| Branches | 311 | 1,074 | 28.96% |
| coverage.py combined statement/branch measure | | | 39.28% |

This is partial structural coverage. Passing all executed cases does not mean every backend path is tested.
Complex relationship construction, many specialized chat/statement branches, and live ingestion/vector-store behavior still have uncovered paths.

The generated reports identify the missing statements and branches.

- [Backend HTML coverage](../test-results/backend/html/index.html)
- [Backend JSON coverage](../test-results/backend/coverage.json)

## Automated acceptance evidence

| ID | Scenario | Result |
| --- | --- | --- |
| UAT-01 | Browser registration, login, logout, and protected-page redirection | Passed |
| UAT-02 | Supported answer, generated title, original source opening, and citation highlighting | Passed |
| UAT-03 | Explicit no-information answer for an unsupported bank-account question | Passed |
| UAT-04 | Controlled timeout, retry recovery, refresh, and no duplicate chat messages | Passed |
| UAT-05 | Folder creation, persisted conversation, refresh, and matching input/card alignment | Passed |
| UAT-06 | A second account cannot display the first account's private conversation | Passed |

[Playwright HTML report](../frontend/playwright-report/index.html) contains per-scenario results and attached screenshots.
Screenshots are also under `frontend/test-results/browser/`.
The original-source and folder screenshots were visually reviewed after the assertions passed.

## Defects and harness issues resolved

1. The chat page wrapped initial folders and conversations in an extra array. This caused temporary blank sidebar rows and React key warnings. The initial state now uses the supplied arrays directly, and a frontend regression test covers it.
2. A missing comma joined two statement-listing phrases. `show statements` and `list all the statements` now use the statement inventory handler. A backend routing regression test covers both phrases.
3. The browser privacy scenario initially read the conversation URL before navigation completed. Its readiness assertion now waits for the persisted conversation URL before attempting access from another account.
4. The browser test file uses an explicit ES-module extension, and teardown verifies ownership before cleaning up the temporary database.

## Remaining acceptance decisions

Human UAT is not signed off. Use [UAT_CHECKLIST.md](UAT_CHECKLIST.md) to record the investigator/product owner's observations and approval.
The live-model case UAT-07 requires a reviewer to check factual answers and contradiction findings against approved sample documents.
The automated controlled-model scenarios do not establish live Ollama accuracy, GPU compatibility, live CIMS/CDR/relationship service behavior, or production HTTPS configuration.

## Reproduction

Use the commands in [TESTING.md](../TESTING.md) to rerun each suite and regenerate the reports.
Generated coverage, browser reports, and screenshots are excluded from Git; rerunning the commands recreates them.
