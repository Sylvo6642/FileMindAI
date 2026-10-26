# FileMind AI

A localhost-only assistant that finds files by describing their contents, not their
filenames. Upload PDFs, Word documents and text files, then ask things like
*"the contract about website maintenance"* or *"which file mentions a payment of 50000
rupees?"*.

Built as a learning project for AI engineering: embeddings, vector databases, hybrid
search, retrieval-augmented generation (RAG), tool calling and agent loops, with no
agent frameworks hiding the mechanics.

**Stack:** Angular 22 · FastAPI · ChromaDB · SQLite · OpenAI `text-embedding-3-small` ·
Claude Haiku (`claude-haiku-5-5`) · PyMuPDF · python-docx · tiktoken

> **Privacy:** FileMind runs on your machine, but it is not offline. The text of every
> uploaded document is sent to **OpenAI** to create embeddings, and excerpts of
> matching documents are sent to **Anthropic** when you search. Don't upload
> documents you are not allowed to share with these providers.

## How it works

1. **Upload:** pick files or a whole folder. FileMind first shows how many tokens each
   file would send to OpenAI and the estimated cost (counted locally, free), and uploads
   only after you confirm. Each file is then validated, its text extracted with
   page/paragraph/line locations, split into ~600-token chunks, and each chunk turned
   into a 1536-number vector stored in ChromaDB.
2. **Search:** Claude reads your question and calls a `search_files` tool. The
   backend combines vector search (meaning) with keyword search (exact words and
   amounts), groups the results by file and returns excerpts.
3. **Answer:** Claude explains which file matches and why. The backend checks that
   every file Claude names was really returned by a tool before showing it.

Details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Measured quality:
[backend/eval/README.md](backend/eval/README.md) (Recall@5 100% on a 35-query test
set with deliberate look-alike documents).

## Requirements (Windows 10/11)

- **Python 3.11**: check with `py -3.11 --version`
- **Node.js 24.15+** and npm: check with `node --version`
- An **OpenAI API key** and an **Anthropic API key**

No Docker, WSL or database server is needed.

## Setup

### Backend

```powershell
cd D:\filemind-ai\backend
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

API keys: the app asks for them on first start (see **Run**). You can also set them
by hand with `copy .env.example .env` and `notepad .env`.

### Frontend

```powershell
cd D:\filemind-ai\frontend
npm install
```

## Run

Use two PowerShell windows.

```powershell
# Window 1: backend on http://127.0.0.1:8000
cd D:\filemind-ai\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --reload-include .env --host 127.0.0.1 --port 8000
```

```powershell
# Window 2: frontend on http://localhost:4200
cd D:\filemind-ai\frontend
npm start
```

Open **http://localhost:4200**. The sidebar footer should say *Backend connected*.

If a key is missing, an **Add your API keys** dialog opens. Paste your
[OpenAI](https://platform.openai.com/api-keys) and
[Anthropic](https://console.anthropic.com/settings/keys) keys. Each key is checked with
its provider for free (a model list request, no tokens) and saved in `backend/.env`;
the browser only ever sees a masked hint like `sk-…a1B2`. You can choose **Later**
and add them from **API keys** in the sidebar footer; until then uploading and
searching stay disabled.

Try the files in `backend/samples/` (their names are deliberately unhelpful).

API docs (Swagger): http://127.0.0.1:8000/docs

## Configuration (`backend/.env`)

| Variable | Default | Meaning |
|---|---|---|
| `OPENAI_API_KEY` | (empty) | Required for uploads and search |
| `EMBEDDING_MODEL` / `EMBEDDING_DIMENSIONS` | `text-embedding-3-small` / `1536` | Changing them starts a new, empty vector collection: reindex your documents |
| `EMBEDDING_PRICE_PER_MILLION` | `0.02` | USD per 1M tokens, only used for the cost shown before uploading |
| `SEARCH_MODE` | `hybrid` | `vector` = embeddings only |
| `ANTHROPIC_API_KEY` | (empty) | Required for the assistant |
| `ANTHROPIC_MODEL` | `claude-haiku-5-5` | |
| `AGENT_EFFORT` | `medium` | `low` / `medium` / `high`: how much Claude thinks |
| `CORS_ORIGINS` | `http://localhost:4200,http://127.0.0.1:4200` | Browser origins allowed to call the API |

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Status and whether API keys are configured |
| GET | `/api/settings/keys` | Which keys are set, with masked hints only |
| PUT | `/api/settings/keys/{openai\|anthropic}` | Check a key with its provider (free) and save it to `.env` |
| POST | `/api/documents/estimate` | Tokens and cost of uploading a file; saves nothing, no OpenAI call |
| POST | `/api/documents/upload` | Upload one file (multipart `file`) |
| GET | `/api/documents` | List documents |
| GET | `/api/documents/{file_id}` | One document's metadata |
| GET | `/api/documents/{file_id}/open` | The original file |
| POST | `/api/documents/{file_id}/reindex` | Retry indexing a failed document |
| DELETE | `/api/documents/{file_id}` | Delete file, vectors and metadata |
| POST | `/api/search` | Ask the assistant (Claude + tools) |
| POST | `/api/search/semantic` | Retrieval only, no Claude |
| GET | `/api/documents/{file_id}/chunks` | *Learning:* how a file was chunked |
| POST | `/api/debug/nearest-chunks` | *Learning:* raw nearest chunks with distances |
| GET | `/api/debug/consistency` | *Learning:* do SQLite, files and vectors agree? |

Errors always look like `{"error": {"code": "...", "message": "..."}}`.

## Testing

| What | Command | Real APIs? |
|---|---|---|
| Backend tests (167) | `cd backend; .\.venv\Scripts\python.exe -m pytest` | No |
| Frontend tests (66) | `cd frontend; npx ng test --watch=false` | No |
| End-to-end check (backend running) | `cd backend; .\.venv\Scripts\python.exe scripts\e2e_check.py` | **Yes**, a few cents |
| Search quality evaluation | `cd backend; .\.venv\Scripts\python.exe eval\run_eval.py [--agent]` | **Yes**. See [eval/README](backend/eval/README.md) |

The end-to-end check uploads two temporary documents (one containing a
prompt-injection attempt), runs real searches, verifies the answers and deletes them.

## Where data is stored

Everything lives in `backend\data\` (excluded from Git):

| Path | Contents |
|---|---|
| `filemind.db` | SQLite: one row per document (name, type, hash, status, counts) |
| `chroma\` | ChromaDB: chunk text, vectors and locations |
| `uploads\` | Your original files, stored as `{file_id}.{ext}` |

To start over, stop the backend and delete `backend\data\`. Don't edit these files
while the backend runs. SQLite, `uploads\` and ChromaDB are reconciled at every
startup; to inspect them without changing anything, open
http://127.0.0.1:8000/api/debug/consistency.

## Windows troubleshooting

| Problem | Fix |
|---|---|
| `Activate.ps1 cannot be loaded because running scripts is disabled` | You don't need activation: call `.\.venv\Scripts\python.exe` directly, as above. (Changing the execution policy is optional and system-wide; FileMind doesn't require it.) |
| `py -3.11` not found | Install Python 3.11 from python.org; the `py` launcher picks the version |
| Port 8000 or 4200 already in use | `Get-NetTCPConnection -LocalPort 8000` shows the owning process; stop it, or use `--port 8001` and update `API_BASE_URL` in `frontend/src/app/core/api.config.ts` |
| Footer says *Backend offline* | Start the backend (window 1). The page rechecks when you switch back to the tab |
| *API key missing* in the footer | Fill `backend\.env`; with `--reload-include .env` the server restarts automatically |
| Delete fails with *file is open in another program* | Windows locks open files: close it in Word/Acrobat and delete again |
| Scanned PDF rejected | Image-only PDFs have no text layer; OCR is not supported |
| Upload shows *Could not reach OpenAI* | Check the key, network and credits, then use **Retry** on the failed document |
| Servers stop when the PC is low on memory | Close other apps, then start them again |

## Project structure

```
filemind-ai/
├── backend/
│   ├── app/
│   │   ├── api/          FastAPI routes
│   │   ├── core/         settings, SQLite, error format
│   │   ├── models/       request/response schemas
│   │   ├── services/     validation, extraction, chunking, embeddings, vectors,
│   │   │                 keyword search, search, agent, consistency
│   │   └── tools/        Claude tools: search_files, inspect_file
│   ├── eval/             evaluation corpus, dataset and runner
│   ├── samples/          sample documents (python scripts\make_samples.py)
│   ├── scripts/          sample generator, end-to-end check
│   └── tests/            pytest suite with fake OpenAI/Claude
├── frontend/src/app/
│   ├── core/             API config, stores (documents, chat), models
│   ├── layout/           sidebar
│   ├── chat/             conversation, assistant message, match cards
│   └── ui/               icons, file badges
└── docs/ARCHITECTURE.md
```

## Limitations

- No OCR: scanned PDFs are rejected.
- Single user, localhost only, no authentication by design.
- The keyword index is rebuilt in memory when documents change. That is fine for
  thousands of chunks; a much larger library would want a persistent full-text index.
- Search quality was measured on a small, self-made dataset; see the caveats in the
  evaluation report.
