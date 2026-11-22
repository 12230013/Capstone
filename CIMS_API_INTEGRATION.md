# CIMS API Integration

## Endpoint

- **Production base URL:** `https://<production-host>` (to be supplied after deployment)
- **Local URL:** `http://127.0.0.1:8001/api/cims/sync`
- **Method:** `POST`
- **Content-Type:** `application/json`
- **Maximum request body:** 1 MiB

The endpoint accepts users, cases, or both. At least one non-empty array is required. Accepted records are appended to the dedicated MongoDB `cims_sync_records` collection as immutable sync batches; the endpoint does not update local user accounts or permissions. Document entries contain metadata only; files are not accepted.

## Authentication and headers

Send the dedicated CIMS token configured in the backend environment as a bearer token:

```http
Authorization: Bearer <CIMS_API_TOKEN>
Content-Type: application/json
```

Requests without a configured server token, or with a missing or incorrect token, receive `401`. Do not send passwords or other authentication credentials in the body.

## Request schema

All top-level and nested objects reject unknown properties. `users` and `cases` are optional nullable arrays; at least one must contain an item. All fields within each record are optional except the identifiers indicated below. Empty arrays are allowed when the other array has records.

### User (`users[]`)

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `user_id` | string | Yes | CIMS user identifier |
| `username` | string | Yes | CIMS username |
| `full_name` | string or null | No | Display name |
| `role` | string or null | No | CIMS role label; stored as received, not applied to local access |
| `permissions` | string array or null | No | CIMS permission labels; stored as received, not applied locally |
| `assigned_cases` | string array or null | No | Assigned case identifiers |
| `is_active` | boolean or null | No | CIMS active status |

### Case (`cases[]`)

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `case_id` | string | Yes | CIMS case identifier |
| `case_number` | string or null | No | Case reference number |
| `case_title` | string or null | No | Case title |
| `case_status` | string or null | No | CIMS case status |
| `registered_date` | `YYYY-MM-DD` string or null | No | Registration date |
| `last_updated` | `YYYY-MM-DD` string or null | No | Last update date |
| `assigned_investigators` | string array or null | No | Assigned CIMS user identifiers |
| `allegation_details` | string or null | No | Allegation description |
| `entities` | entity array or null | No | People or organizations associated with the case |
| `interviews` | interview array or null | No | Interview metadata and statement text |
| `case_events` | event array or null | No | Investigation events |
| `documents` | document metadata array or null | No | Metadata for statements, reports, exhibits, evidence, and other investigation documents; no file content |

Nested object fields:

| Object | Required fields | Optional fields |
| --- | --- | --- |
| Entity | `entity_id` (string) | `name`, `cid`, `phone_number`, `nationality`, `gender`, `entity_type`, `involvement` (string or null); `dob` (`YYYY-MM-DD` or null) |
| Interview | `interview_id` (string) | `entity_id`, `interviewee_name`, `interviewee_type`, `interview_location`, `statement_text` (string or null); `interview_date` (`YYYY-MM-DD` or null); `interview_time` (`HH:MM:SS` or null); `document_ids` (string array or null) |
| Case event | `event_id` (string) | `event_name`, `description` (string or null); `event_date` (`YYYY-MM-DD` or null) |
| Document | `document_id`, `file_name` (string) | `document_type`, `file_format` (string or null); `created_at`, `last_updated` (`YYYY-MM-DD` or null) |

CID and phone numbers are strings to preserve leading zeros and non-numeric formatting. Date/time values use ISO formats. Nullable fields may be omitted or set to `null`.

## Example request

```json
{
  "users": [
    {
      "user_id": "U001",
      "username": "investigator01",
      "full_name": "Investigator A",
      "role": "investigator",
      "permissions": ["view_case"],
      "assigned_cases": ["CASE_001"],
      "is_active": true
    }
  ],
  "cases": [
    {
      "case_id": "CASE_001",
      "case_number": "19/2025-26",
      "case_title": "Example Investigation",
      "case_status": "Ongoing",
      "registered_date": "2026-08-01",
      "last_updated": "2026-11-19",
      "assigned_investigators": ["U001"],
      "allegation_details": "Description of the allegation",
      "entities": [
        {
          "entity_id": "ENT001",
          "name": "Person A",
          "cid": "00123456789",
          "phone_number": "+97517123456",
          "dob": "1990-05-15",
          "nationality": "Bhutanese",
          "gender": "Female",
          "entity_type": "Person",
          "involvement": "Witness"
        }
      ],
      "interviews": [
        {
          "interview_id": "INT001",
          "entity_id": "ENT001",
          "interviewee_name": "Person A",
          "interviewee_type": "Witness",
          "interview_date": "2026-09-12",
          "interview_time": "10:30:00",
          "interview_location": "ACC Office, Thimphu",
          "statement_text": "Example witness statement",
          "document_ids": ["DOC001"]
        }
      ],
      "case_events": [
        {
          "event_id": "EV001",
          "event_name": "Witness Interview",
          "event_date": "2026-09-12",
          "description": "Example investigation event"
        }
      ],
      "documents": [
        {
          "document_id": "DOC001",
          "file_name": "witness_statement.pdf",
          "document_type": "Witness Statement",
          "file_format": "pdf",
          "created_at": "2026-09-12",
          "last_updated": "2026-11-19"
        }
      ]
    }
  ]
}
```

## Responses

Successful storage returns `200`:

```json
{
  "status": "success",
  "message": "CIMS data received successfully",
  "users_received": 1,
  "cases_received": 1
}
```

Errors use FastAPI's `detail` response shape:

| Status | Example detail | Meaning |
| --- | --- | --- |
| `401` | `Missing or invalid API token.` | Missing/invalid bearer token or server token not configured |
| `413` | `Request body exceeds the 1 MiB limit.` | Request is too large |
| `422` | `At least one user or case is required.` | Both arrays are empty or omitted; schema errors also return `422` |
| `500` | `CIMS data could not be stored.` | Database storage failed |

## Local testing

1. Set a private value for `CIMS_API_TOKEN` in `backend/.env` (for example, generate one with `python -c "import secrets; print(secrets.token_urlsafe(32))"`). Do not commit `.env` or share the token.
2. Start MongoDB and the FastAPI backend as described in the repository README.
3. Open `http://127.0.0.1:8001/docs`, expand **CIMS Integration**, select **Authorize**, and enter the token. Submit the example JSON to `POST /api/cims/sync`.
4. In Postman, create a `POST` request to `http://127.0.0.1:8001/api/cims/sync`, set **Authorization → Bearer Token**, set **Body → raw → JSON**, and submit the example.

Use `{"users":[{"user_id":"U001","username":"investigator01"}]}` for a user-only request, or `{"cases":[{"case_id":"CASE_001"}]}` for case-only. Multiple items may be sent in either array.
