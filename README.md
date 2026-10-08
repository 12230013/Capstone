Installation

1. Clone the Repository
git clone <repository-url>
cd chatbot/backend

2. Create a Virtual Environment
python -m venv .venv

Activate it on Windows:
.venv\Scripts\activate

3. Install Deoendencies
pip install -r requirements.txt

4. Configure Environment Variables
Create a .env file based on .env.example.

Example:

CDR_API_BASE_URL=http://172.21.48.162:5000
CDR_API_TIMEOUT=15

Do not commit .env or confidential investigation documents to the repository.

Ollama Setup
- Install Ollama and make sure it is available from the terminal
Verify: ollama --version
Start the ollama server: ollama serve

The project currently uses: mistral:7b-instruct-v0.3-q2_K

Running the Backend
uvicorn app.main:app --reload
The API will be available at:

http://127.0.0.1:8000

FastAPI documentation:

http://127.0.0.1:8000/docs


## Project Structure

backend/
│
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   │
│   ├── document_processing/
│   │   ├── __init__.py
│   │   ├── document_loader.py
│   │   ├── text_cleaner.py
│   │   └── text_chunker.py
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── embedding_service.py
│   │   ├── qdrant_service.py
│   │   ├── ingestion_service.py
│   │   ├── retrieval_service.py
│   │   ├── prompt_service.py
│   │   ├── llm_service.py
│   │   └── rag_service.py
│   │
│   ├── analytics/
│   │   ├── __init__.py
│   │   └── cdr_analytics.py
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   └── cdr.py
│   │
│   └── utils/
│       ├── __init__.py
│       └── cdr_utils.py
│
├── test_documents/
│   └── case_004.txt
│
├── qdrant_storage/
│
├── test_ingestion.py
├── test_retrieval.py
├── test_rag_service.py
├── test_qdrant_count.py
├── test_multi_ingestion.py
├── test_multi_retrieval.py
│
├── .env
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md

 `app/`

The main application package. All backend functionality is organized inside this folder.

---

 `app/main.py`

The **main entry point of the FastAPI backend**.

It:

* Creates the FastAPI application
* Registers API endpoints
* Handles chatbot requests
* Registers CDR endpoints
* Connects the API layer with the services

The main chatbot endpoint is:

POST /api/chat

 `app/config.py`

Contains application configuration and environment-related settings.

This is where configuration values can be centralized instead of hard-coding them throughout the application.

`app/document_processing/`

Contains everything related to preparing investigation documents before they are stored in the vector database.

`document_loader.py`

Loads supported document formats:

* PDF
* DOCX
* TXT

It extracts the text and basic document metadata.

Flow:

Document
   ↓
document_loader.py
   ↓
Extracted text

 `text_cleaner.py`

Cleans extracted text before further processing.

It handles things such as:

* Extra spaces
* Unnecessary whitespace
* Paragraph formatting

Flow:

Extracted text
      ↓
text_cleaner.py
      ↓
Clean text

`text_chunker.py`

Splits cleaned documents into smaller, meaningful pieces called **chunks**.

The chunker is sentence-aware and uses overlap so that important context is not lost between chunks.

Current configuration:

Chunk size: 500
Overlap: 50

Flow:

Clean document
      ↓
text_chunker.py
      ↓
Chunk 1
Chunk 2
Chunk 3

 `app/services/`

Contains the main services used by the RAG chatbot.

 `embedding_service.py`

Creates vector embeddings using:

Sentence Transformers
all-MiniLM-L6-v2

It converts text into numerical vectors so that semantically similar text can be searched.

Example:

"What financial transaction was discussed?"
                  ↓
             Embedding
                  ↓
          [384-dimensional vector]


`qdrant_service.py`

Handles communication with the Qdrant vector database.

It is responsible for:

* Creating the collection
* Storing document chunks
* Storing embeddings
* Searching for similar vectors

Current collection:

investigation_documents

`ingestion_service.py`

Connects the document-processing components together.

This is the main **document ingestion pipeline**:

Document
   ↓
Load
   ↓
Clean
   ↓
Chunk
   ↓
Embed
   ↓
Qdrant

It uses:

document_loader.py
text_cleaner.py
text_chunker.py
embedding_service.py
qdrant_service.py

The service also creates deterministic IDs for chunks to prevent duplicate documents from being stored when the same document is ingested again.

 `retrieval_service.py`

Handles retrieval of relevant evidence from Qdrant.

The normal process is:

User Query
    ↓
Query Embedding
    ↓
Qdrant Search
    ↓
Relevant Chunks

It also contains **case-aware retrieval**.

For example:

Investigation Case 004
        ↓
Detect case number
        ↓
Retrieve relevant chunks
        ↓
Prioritize case_004.txt

This prevents a semantically similar document from another investigation case from being prioritized over the case explicitly requested by the investigator.

 `prompt_service.py`

Builds the prompt sent to the local LLM.

The prompt instructs the model to:

* Use only the provided investigation evidence
* Avoid outside knowledge
* Avoid inventing information
* Avoid mixing unrelated cases
* Indicate when evidence is insufficient
* Consider the specified investigation case

Flow:

Retrieved Evidence
        +
User Question
        ↓
prompt_service.py
        ↓
LLM Prompt

`llm_service.py`

Handles communication with the local LLM through Ollama.

Current model:

mistral:7b-instruct-v0.3-q2_K

The service sends the constructed prompt to Ollama and returns the generated response.

Flow:

Prompt
  ↓
Ollama
  ↓
Mistral
  ↓
Generated Answer

 `rag_service.py`

Combines the individual RAG components into one complete workflow.

It connects:

Retrieval
    ↓
Prompt Construction
    ↓
Mistral
    ↓
Answer
    ↓
Sources

It also performs **case-aware source filtering**.

For example, if the user asks about Case 004:

Retrieved:
case_004.txt
case_002.txt
case_003.txt

        ↓
Case filtering

        ↓

Returned:
case_004.txt

This ensures unrelated investigation cases are not returned as supporting sources.


`app/analytics/`

Contains analytical functionality that is separate from the RAG document pipeline.

 `cdr_analytics.py`

Contains the analytical logic for CDR data.

Current capabilities include:

* Communication frequency
* Communication direction
* Date-range analysis
* Period statistics
* Communication timeline
* Contact interaction analysis
* Irregular communication patterns
* Communication network generation

The CDR analytics identify communication patterns and indicators. They do not automatically determine that a communication is suspicious.


`app/models/`

Contains data models used by the backend.

`cdr.py`

Contains models used for representing and validating CDR-related data.

Using models keeps the API data structure consistent.

 `app/utils/`

Contains reusable helper functions.

 `cdr_utils.py`

Contains utility functions used by the CDR functionality, such as processing and formatting CDR-related data.

 `test_documents/`

Contains documents used for local development and testing.

Example:

test_documents/
└── case_004.txt

These are **test documents only**.

Actual confidential investigation documents should not be committed to Git.

 `qdrant_storage/`

Local storage used by Qdrant during development.

This contains the locally stored vector database data.

It is generated/maintained by Qdrant and should generally not be manually edited.

Test Files

The test scripts are currently kept in the backend root for development.
 `test_ingestion.py`

Tests the complete document ingestion pipeline:


Load → Clean → Chunk → Embed → Qdrant


 `test_retrieval.py`

Tests semantic and case-aware retrieval.

`test_rag_service.py`

Tests the complete RAG service:

Retrieval → Prompt → Mistral → Answer

`test_qdrant_count.py`

Checks the number of points stored in the Qdrant collection.

Useful for verifying that duplicate ingestion is not creating duplicate vectors.

 `test_multi_ingestion.py`

Tests ingestion of multiple documents.

 `test_multi_retrieval.py`

Tests retrieval across multiple investigation documents.



 Configuration Files

`.env`

Contains local environment configuration such as the CDR API connection.

Example:

CDR_API_BASE_URL=http://172.21.48.162:5000
CDR_API_TIMEOUT=15

**Do not commit `.env` to Git.**

 `.env.example`

Template showing which environment variables are required without exposing actual credentials or configuration values.


 `.gitignore`

Specifies files and folders that should not be committed to the repository.

This should include things such as:

.venv/
.env
__pycache__/
qdrant_storage/

Confidential investigation documents should also be excluded.

 `requirements.txt`

Contains the Python dependencies required to run the backend.


Overall RAG Flow

The main RAG components work together as follows:

                 DOCUMENT INGESTION

Document
   ↓
document_loader.py
   ↓
text_cleaner.py
   ↓
text_chunker.py
   ↓
embedding_service.py
   ↓
qdrant_service.py
   ↓
Qdrant

When an investigator asks a question:

                  QUESTION ANSWERING

User Question
      ↓
retrieval_service.py
      ↓
Case-Aware Retrieval
      ↓
Relevant Evidence
      ↓
prompt_service.py
      ↓
llm_service.py
      ↓
Mistral
      ↓
rag_service.py
      ↓
Answer + Sources
      ↓
/api/chat


Current Development Status

 Completed

* Document loading
* Text cleaning
* Sentence-aware chunking
* Metadata handling
* Embeddings
* Qdrant storage
* Duplicate ingestion prevention
* Semantic retrieval
* Case-aware retrieval
* Prompt construction
* Local Mistral integration
* RAG service
* `/api/chat`
* Case-aware source filtering
* CDR analytics
* Relationship mapping API

Currently Being Developed

* Statement summarization
* Key entity extraction
* Chronological timeline generation
* Contradiction detection
* Automatic document ingestion from the actual ACC/CIMS source
* Authentication and RBAC

## Tesseract OCR and frontend

The OCR endpoints are mounted in the existing backend without replacing its chat,
CDR, or relationship routes. Uploaded PDF/image files, SQLite metadata, and OCR
result JSON are runtime data under `backend/data/` and are ignored by Git.

Install the Python packages from the backend root:

```powershell
cd backend
python -m pip install -r requirements.txt -r requirements-ocr.txt
```

Install native Tesseract OCR separately (it is not a Python package). On Windows,
install Tesseract OCR, ensure `tesseract --version` works in PowerShell, or set
`TESSERACT_CMD` in `backend/.env` to the full path of `tesseract.exe`. Start the
existing API as usual with `uvicorn app.main:app --reload`; Swagger is available
at `http://127.0.0.1:8000/docs`.

`POST /documents/upload` accepts PDF, PNG, JPG, or JPEG uploads. PDFs with
selectable text are detected and read using page-preserving direct extraction.
Scanned PDFs are marked as requiring OCR; OCR is run only by explicitly calling
`POST /documents/{document_id}/ocr`. Image uploads can also be OCR'd explicitly.
Preprocessing is configurable through the `OCR_*` settings in `.env.example`;
the original uploaded file is preserved.

The basic upload endpoints do not yet authenticate uploaders or enforce case
access. Use synthetic/test documents only until team authentication and access
control are connected to these routes.

To run the frontend, open another terminal:

```powershell
cd frontend
npm ci
npm run dev
```

The Vite development server proxies `/documents` to the backend on port 8000.
Run frontend checks with `npm run lint` and `npm run build`.

The OCR tests use only generated synthetic documents:

```powershell
cd backend
python -m unittest discover -s tests
python tools/evaluate_ocr_preprocessing.py
```

The evaluation script requires the native Tesseract executable and reports
character error rates for baseline and preprocessed synthetic samples; it does
not use ACC documents.