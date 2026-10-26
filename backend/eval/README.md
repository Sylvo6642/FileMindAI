# Search evaluation

How well does FileMind find the right file? This folder answers that with numbers
instead of impressions.

```powershell
cd D:\filemind-ai\backend
.\.venv\Scripts\python.exe eval\run_eval.py                 # retrieval only (cheap: embeddings)
.\.venv\Scripts\python.exe eval\run_eval.py --mode vector   # embeddings only, for comparison
.\.venv\Scripts\python.exe eval\run_eval.py --agent         # full Claude agent (~215k tokens)
.\.venv\Scripts\python.exe eval\run_eval.py --only q25,q28  # just some queries
```

The script indexes the corpus into a **temporary** folder with the real OpenAI
embeddings, so your library in `backend/data` is never touched. Each run saves its
details to `eval/results/` (ignored by Git).

## What is measured

| File | Purpose |
|---|---|
| `corpus/` + `../samples/` | 16 documents. 11 are deliberate *distractors* that look like the originals: a consulting agreement next to the software agreement, an offer letter next to the employment contract, a support-renewal invoice next to the annual fees table, a ₹25,000 rent receipt next to the ₹50,000 payment note. Without near-misses every query would trivially succeed. |
| `dataset.json` | 35 queries with the correct file(s). Categories: `exact`, `paraphrase`, `detail`, `numeric`, `multi`, `no_match`. |

**Metrics** (over the 32 queries that have a correct answer):

- **Recall@5**: share of queries where a correct file is in the top 5. This is the
  number that matters for an agent: Claude can only pick a file it is shown.
- **Hit@1**: share where a correct file is ranked first.
- **MRR** (mean reciprocal rank): 1 for rank 1, ½ for rank 2, ⅓ for rank 3… 0 if missing.
- Agent only: **recall** (Claude named a correct file), **precision** (share of the
  files Claude named that are correct) and **no-match accuracy** (Claude named
  nothing when nothing matches).

## Results (2026-10-26, text-embedding-3-small, claude-haiku-5-5)

| Search mode | Recall@5 | Hit@1 | MRR | Agent recall | Agent precision | No-match |
|---|---|---|---|---|---|---|
| vector only | 93.8% | 87.5% | 0.901 | 93.8% | 93.3% | 3/3 |
| **hybrid (default)** | **100%** | **90.6%** | **0.948** | **100%** | **96.9%** | **3/3** |

Per category, vector only: `exact`, `paraphrase` and `multi` were already 100%. All the
misses were **numeric**:

| Query | Document text | Vector only | Hybrid |
|---|---|---|---|
| payment of 50000 rupees | "advance payment of ₹50,000" | not in top 5 | rank 3 |
| project budget of 32 lakh rupees | "INR 32,00,000" | not in top 5 | rank 2 |

When the right file was missing, Claude answered "no matching document" instead of
guessing. That is the honest failure mode we designed for, but still a miss.

## Decision: hybrid search

Embeddings represent *meaning*; they do not reliably know that `50000`, `50,000`
and `₹50,000` are the same number, or that `32 lakh` is `32,00,000`. Keyword search
is exact about tokens but blind to meaning. Hybrid search uses both:

1. **BM25 keyword ranking** over the chunk text (`app/services/lexical_service.py`),
   after normalising numbers: digit groups are joined (`1,23,900` → `123900`) and
   Indian units are expanded (`32 lakh` → `3200000`, `1.5 crore` → `15000000`).
2. **Reciprocal Rank Fusion** (`app/services/search_service.py`): each file scores
   `1 / (60 + rank)` in each ranking it appears in, summed. RRF uses only ranks, so
   BM25 scores and cosine distances never have to be put on one scale.

It fixed both misses, improved MRR, and caused no regressions in any category, so it
is the default. Set `SEARCH_MODE=vector` in `backend/.env` to compare.

## Honest caveats

- **Small dataset.** 32 answerable queries: one query is ~3 percentage points. Treat
  differences of one query as noise.
- **Written by the builder.** The number normalisation was added after seeing the two
  numeric failures. That is how evals are meant to be used, but it risks tuning to
  this exact set. Add your own queries (especially on your own documents) to check
  it generalises.
- **Hit@1 is still 90.6%.** Remaining rank-2/3 cases are near-ties between similar
  documents (e.g. "sixty days notice" vs an offer letter with "ninety days" notice).
  Claude reads the excerpts and still picks correctly, which is why agent recall is
  100% while Hit@1 is not.
- **No-match is decided by Claude, not by a threshold.** No-match queries scored
  up to 0.37 similarity while some correct top results scored only 0.23, so no
  similarity cutoff can separate them.
- **Cost.** Retrieval-only runs cost a fraction of a cent. An `--agent` run used
  ~215k tokens.

## Adding a query

Append to `dataset.json`:

```json
{"id": "q36", "category": "paraphrase", "query": "your question", "expected": ["file.txt"]}
```

`expected: []` means no document should match. New documents go in `corpus/`.
