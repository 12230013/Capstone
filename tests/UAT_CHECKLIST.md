# User acceptance testing checklist

Automated browser checks exercise the acceptance scenarios below. Actual user acceptance requires an investigator or product owner to review the behavior and sign off.

## Review record

- Tester / role: ____________________
- Date: ____________________
- Build or commit: ____________________
- Environment: ____________________
- Overall decision: Accepted / Accepted with issues / Rejected
- Comments: ____________________

## Test data

The automated data is in `tests/fixtures/acceptance.json`.
Each automated scenario creates a unique synthetic account. The document states that Pema Dorji owns a demonstration sawmill.
It includes no bank account number. The retry scenario deliberately simulates one temporary model timeout.

## Acceptance cases

| ID | Steps | Expected result | Automated scenario | Human review |
| --- | --- | --- | --- | --- |
| UAT-01 | Register, sign in, sign out, then open the dashboard again | Registration works, the authenticated workspace opens, logout revokes access, and the protected page requires sign-in | `acceptance.spec.mjs` UAT-01 | Pending |
| UAT-02 | Ask who owns the demonstration sawmill, open Sources, select the statement | The answer matches the source, the generated title appears, the original document opens, and cited text is highlighted | `acceptance.spec.mjs` UAT-02 | Pending |
| UAT-03 | Ask for the owner's bank account number | The assistant explicitly states that the available documents do not contain the information | `acceptance.spec.mjs` UAT-03 | Pending |
| UAT-04 | Submit the controlled timeout question, retry, then refresh | An error is visible, the question can be retried, only one successful exchange appears, and refresh preserves that exchange | `acceptance.spec.mjs` UAT-04 | Pending |
| UAT-05 | Create a folder, submit a question from it, return to the folder, then refresh | The conversation remains in the folder and the input aligns with its conversation cards | `acceptance.spec.mjs` UAT-05 | Pending |
| UAT-06 | Open one account's private conversation URL while signed in as another account | Access is refused and the other account's answer is not displayed | `acceptance.spec.mjs` UAT-06 | Pending |
| UAT-07 | In an approved staging environment, ask supported, missing-information, and contradiction questions over known sample investigation documents with the real model | Facts and citations match the documents, missing facts are acknowledged, and compatible facts are not falsely labelled contradictions | Human-led live-model review | Pending |

## Acceptance limits

The browser suite uses real React pages, FastAPI HTTP requests, HttpOnly cookies, MongoDB persistence, and local source files.
The external model and embedding calls are controlled test doubles so the scenarios are reproducible.
A passing automated scenario does not establish the real model's factual accuracy or provide business-owner approval.
Record the investigator's judgments, defects, and final acceptance decision above.
