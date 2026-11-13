# ACC Investigation Support Assistant

An investigation support chatbot for the Anti-Corruption Commission. It combines a React interface with a FastAPI backend, local document retrieval, and answer generation through Ollama.

The assistant supports document questions with source references, CDR analysis, and relationship queries. It also provides conversation folders, automatic chat titles, activity history, and authenticated sessions.

> This AI assistant is a support tool and may provide inaccurate information. Always apply professional judgment when using its responses.

## Technology

- **Frontend:** React, Vite, React Router, and Lucide icons.
- **Backend:** Python and FastAPI.
- **Persistence:** MongoDB for accounts, sessions, conversations, folders, and activity logs.
- **Document search:** Local Qdrant storage and BAAI/bge-m3 embeddings for the statement pipeline.
- **Answer generation:** A local Ollama model, selected with `OLLAMA_MODEL`.
- **Testing:** Python unittest, FastAPI TestClient, Vitest, React Testing Library, and Playwright.

## Local setup

The commands below use PowerShell in VS Code. Start from the repository root unless a step changes the directory.

Install Python, Node.js with npm, MongoDB, and Ollama first. MongoDB must be running before signing in or using chat persistence.

### 1. Backend environment

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Copy the environment template only when creating a new local configuration; keep an existing `.env`.

The current `requirements.txt` contains conflicting duplicate pins for FastAPI and python-dotenv. A clean installation may fail until those versions are reconciled; an existing working environment does not verify a fresh install.

Edit `backend/.env` for your machine. The main settings are:

| Setting | Purpose |
| --- | --- |
| `MONGO_URI` | MongoDB connection; defaults to `mongodb://localhost:27017` |
| `MONGO_DB_NAME` | Application database; defaults to `acc_database` |
| `OLLAMA_MODEL` | Installed Ollama model used for answers |
| `OLLAMA_NUM_GPU` | `-1` for automatic GPU use, or `0` for CPU mode |
| `CDR_API_BASE_URL` | External CDR service address |
| `RELATIONSHIP_API` | External relationship service address |
| `FRONTEND_ORIGINS` | Allowed frontend origins for cookies and requests |
| `SESSION_HOURS` / `SESSION_IDLE_MINUTES` | Session expiry limits |
| `ENVIRONMENT` / `SESSION_COOKIE_SECURE` | Deployment environment and secure-cookie configuration |

See [backend/.env.example](backend/.env.example) for the template. CDR and relationship features require their respective services and data.

### 2. Ollama

Pull the model configured in `.env`. For the model in the supplied template:

```powershell
ollama pull mistral:7b-instruct-v0.3-q2_K
ollama list
```

Ollama must be running at `http://localhost:11434`. If it is not already running through the desktop application, start it in another terminal:

```powershell
ollama serve
```

Model choice and available memory affect response time. The embedding model also uses memory, and its first use downloads model files.

### 3. Local statement documents

The current statement workflow uses manually supplied documents; automatic CIMS document ingestion is not connected.

Place statement `.txt` files in `backend/acc_statements/data/statements/`, following the format documented in [StatementAnalysis.md](backend/acc_statements/StatementAnalysis.md). From `backend`, parse and index them:

```powershell
.\.venv\Scripts\python.exe -m acc_statements.main ingest
.\.venv\Scripts\python.exe -m acc_statements.main index
```

Stop the backend before running indexing commands because both use the local Qdrant database. Parsed output and the index remain local and are excluded from Git.

### 4. Start the backend

From `backend`:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

- API: http://127.0.0.1:8000
- Interactive API documentation: http://127.0.0.1:8000/docs

Startup loads and warms the document embedding model. Wait for startup to complete before submitting questions.

### 5. Start the frontend

In a separate terminal, from the repository root:

```powershell
cd frontend
npm.cmd ci
npm.cmd run dev
```

Open the local URL printed by Vite, normally http://localhost:5173. Register an account and sign in. During development, the frontend connects to port 8000 on the same hostname; `VITE_API_BASE_URL` can override this.

## Sources and sessions

Answers expose a Sources button that opens a panel on the right. Source entries use backend metadata and can display the available original document with cited sentences highlighted. When the original file is unavailable, the retrieved passage provides the available evidence.

Document answers use evidence checks and should report insufficient information when supporting material is missing. These safeguards do not replace investigator review.

Authentication uses server-side sessions with HttpOnly cookies, CSRF protection, expiry, and account ownership checks. HTTPS deployments require secure cookies and matching allowed frontend origins.

## Project structure

| Path | Purpose |
| --- | --- |
| `frontend/src/` | React pages, shared components, styles, and API client |
| `frontend/e2e/` | Browser acceptance tests |
| `backend/app/` | FastAPI routes, authentication, database access, and application services |
| `backend/acc_statements/` | Statement parsing, indexing, retrieval, and analysis |
| `backend/tests/` | Backend unit, API, security, and structural tests |
| `backend/integration_tests/` | Workflows using a real, isolated MongoDB test database |
| `tests/` | Synthetic fixtures, recorded test results, and the manual UAT checklist |
| `TESTING.md` | Test setup, commands, coverage reports, and scope |

## Testing

Run backend unit/API tests from the repository root:

```powershell
.\backend\.venv\Scripts\python.exe -m unittest discover -s backend/tests -v
```

Run frontend unit/component tests:

```powershell
cd frontend
npm.cmd test
npm.cmd run build
```

See [TESTING.md](TESTING.md) for MongoDB integration tests, Playwright browser tests, and coverage commands. Recorded results are in [tests/TEST_RESULTS.md](tests/TEST_RESULTS.md); manual acceptance checks are in [tests/UAT_CHECKLIST.md](tests/UAT_CHECKLIST.md).

Automated tests use synthetic data and controlled model responses. Live model quality and human acceptance require separate review.

## Files to keep local

Do not commit `.env`, confidential investigation documents, local databases, virtual environments, dependencies, or generated test reports. These are covered by `.gitignore`. Commit the environment template, source tests, synthetic fixtures, lockfiles, and testing documentation.
