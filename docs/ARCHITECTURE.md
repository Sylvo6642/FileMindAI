# FileMind AI architecture

FileMind finds documents by describing their contents. Everything runs on your
machine except two API calls: OpenAI (embeddings) and Anthropic (Claude).

```
 Browser (Angular, :4200)                      FastAPI backend (127.0.0.1:8000)
┌──────────────────────────┐   HTTP/JSON   ┌───────────────────────────────────────────┐
│ Sidebar: library, upload │ ────────────▶ │ api/            routes, validation, errors │
│ Chat: question → answer  │ ◀──────────── │ services/       ingestion, search, agent   │
│ Match cards, open file   │               │ tools/          search_files, inspect_file │
└──────────────────────────┘               └───┬──────────────┬─────────────┬──────────┘
   no API keys in the browser                  │              │             │
                                     ┌─────────▼───┐  ┌───────▼──────┐  ┌───▼──────────┐
                                     │ SQLite      │  │ ChromaDB     │  │ uploads/     │
                                     │ filemind.db │  │ chroma/      │  │ originals    │
                                     │ metadata    │  │ chunk vectors│  │ {uuid}.{ext} │
                                     └─────────────┘  └──────────────┘  └──────────────┘
                                                 OpenAI embeddings ◀─┘   Anthropic Claude
```

All runtime data lives in `backend/data/` (excluded from Git).

## 1. Ingestion: upload → indexed

`services/document_service.py: ingest_upload`

| Step | Code | Why |
|---|---|---|
| 1. Sanitise name, check extension, size (20 MB), real content (PDF magic bytes, DOCX zip structure, text not binary) | `validation_service.py` | Never trust the filename or the browser |
| 2. SHA-256 of the bytes; reject if already stored | `metadata_service.get_document_by_hash` | Duplicate under any name |
| 3. Extract text **with locations**: PDF pages, DOCX paragraphs/tables/sections, TXT lines | `extraction_service.py` | Results can cite "page 4" |
| 4. Split into ~600-token chunks with 100-token overlap, at sentence boundaries | `chunking_service.py` (tiktoken) | Embeddings work best on focused passages; overlap keeps sentences that cross a boundary |
| 5. Save the original as `{uuid}.{ext}`, insert SQLite row `pending` | `document_service.py` | Paths are built from a UUID, never from user input |
| 6. `processing` → embed chunks (batches of 100) → upsert to Chroma → `indexed` (or `failed`, retryable) | `embedding_service.py`, `vector_service.py` | Everything that can fail on bad input runs *before* anything is written |

Steps 1–4 happen in memory, so a rejected upload leaves nothing behind.

## 2. Search: question → verified answer

```
question ──▶ Claude Haiku (agent loop, max 5 tool rounds)
               │ search_files(query, limit)         ◀─ Claude writes the query
               ▼
          ┌─ embed query (same model as documents) ─▶ Chroma: nearest chunks (cosine)
 hybrid ──┤                                              drop distance > 0.85
          └─ BM25 keyword ranking over chunk text (numbers normalised)
               ▼
          Reciprocal Rank Fusion → group by file → top 5 files + excerpts with locations
               │
               ▼  (Claude may search again, or inspect_file(file_id) for a closer look)
          final JSON {answer, matches[{file_id, reason}]}
               ▼
          backend keeps only file_ids a tool actually returned AND that exist
               ▼
          UI: answer, tool steps, match cards (sim = 1 − cosine distance)
```

- **Retrieval** (`search_service.py`, `lexical_service.py`) decides *which files are
  candidates*. **Reasoning** (`agent_service.py`) decides *which candidates actually
  answer the question*, and says so when none do. This split is RAG.
- **Hybrid search** exists because the evaluation showed embeddings missing exact
  amounts (`50000` vs `₹50,000`). See `backend/eval/README.md`.
- **Similarity is not confidence.** It is a ranking signal; the UI shows `sim 0.42`,
  never "42%".

## 3. The agent loop

`services/agent_service.py: run_search_agent`

1. Send the question with two tool definitions (`tools/file_tools.py`, strict schemas).
2. If Claude asks for tools, run them **in our code** (validated with Pydantic) and
   send all results back in one message. Claude never touches the filesystem.
3. After 5 tool rounds, tools are switched off (`tool_choice: none`) so it must answer.
4. The final answer must match a JSON schema; its file_ids are verified (step above).

## 4. Security layers

| Threat | Defence |
|---|---|
| API key leaks | Keys live only in `backend/.env`. A key typed in the app goes once to the local backend, which checks it with its provider and saves it; responses only ever carry a masked hint. Writing keys is refused for other browser origins, and malformed values (spaces, newlines) are rejected so `.env` cannot be injected |
| Malicious upload | Extension allowlist, content checks, size limit, DOCX zip-bomb check, sanitised names, UUID storage paths |
| Path traversal | `stored_path()` builds paths from a validated UUID and checks they stay inside `uploads/` |
| Prompt injection inside a document | Document text is labelled untrusted in tool results; system prompt says to ignore instructions in documents; **file_ids are verified in code**, so a document cannot make Claude cite a file it never retrieved |
| Hallucinated files | Same verification: only tool-returned, existing files reach the UI |
| Other websites calling the API | Bound to 127.0.0.1; CORS allows only the Angular dev origin |

## 5. Keeping the three stores in agreement

Each document lives in SQLite, `uploads/` and Chroma. `consistency_service.py`
reconciles them at every startup (orphan files and vectors removed; documents with a
missing original or partial vectors marked `failed`). Read-only report:
`GET /api/debug/consistency`.

## 6. Key settings (`app/core/config.py`)

| Setting | Value | Notes |
|---|---|---|
| Embedding model | `text-embedding-3-small`, 1536 dims | Collection is named after model+dims, so vectors never mix |
| Chunk size / overlap | 600 / 100 tokens | |
| Distance cutoff | 0.85 | Removes nonsense only; "no match" is Claude's call |
| `SEARCH_MODE` | `hybrid` | `vector` to compare |
| Agent | `claude-haiku-5-5`, effort `medium`, max 5 tool rounds | |

## 7. Tests

| Layer | Where | External APIs |
|---|---|---|
| Backend unit + API (167 tests) | `backend/tests/` | Faked (bag-of-words embedder, scripted Claude) |
| Frontend (66 tests) | `frontend/src/**/*.spec.ts` | Faked HTTP backend |
| End-to-end, live | `backend/scripts/e2e_check.py` | Real |
| Search quality | `backend/eval/run_eval.py` | Real |
