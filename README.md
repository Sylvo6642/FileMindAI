# FileMind AI

A localhost-only assistant that finds files by describing their contents, not their filenames.

Built with FastAPI, Angular, ChromaDB, OpenAI embeddings and Claude Haiku tool calling.

> Work in progress. Full documentation arrives in Stage 8.

## Requirements (Windows)

- Python 3.11 (`py -3.11 --version`)
- Node.js 24.15+ and npm

## Backend

```powershell
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Add `--reload-include .env` to also restart the server when you edit `.env`.

If `Activate.ps1` is blocked by execution policy, skip activation and call the venv's
Python directly: `.\.venv\Scripts\python.exe -m uvicorn ...`

> **Privacy:** uploaded document text is sent to OpenAI to generate embeddings.

Tests: `python -m pytest`

## Frontend

```powershell
cd frontend
npm install
npm start
```

Open http://localhost:4200.
