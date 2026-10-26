"""Measure search quality on a fixed set of queries with known answers.

Builds a throwaway index of the eval corpus (backend/samples + eval/corpus) with
the REAL OpenAI embeddings, then runs every query in eval/dataset.json.

    python eval/run_eval.py            retrieval only (vector search, no Claude)
    python eval/run_eval.py --agent    also run the full Claude agent on each query
    python eval/run_eval.py --mode vector   embeddings only (default: SEARCH_MODE, i.e. hybrid)

Your real library in backend/data is never touched.

Metrics (computed over queries that have a correct answer):
  Recall@k  share of queries whose correct file is in the top k results
  Hit@1     share of queries whose correct file is ranked first
  MRR       mean reciprocal rank: 1 for rank 1, 0.5 for rank 2, ... 0 if missing
For the agent, also:
  Precision   share of the files Claude named that are actually correct
  No-match    share of no_match queries where Claude correctly named no file
"""

import argparse
import json
import logging
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import settings  # noqa: E402
from app.core.database import init_db  # noqa: E402
from app.services import agent_service, document_service, search_service  # noqa: E402
from app.services.agent_service import AgentError  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parent
CORPUS_DIRS = [BACKEND_DIR / "samples", EVAL_DIR / "corpus"]
SKIP = {"scan_0001.pdf"}  # image-only: rejected at upload by design
RESULTS_DIR = EVAL_DIR / "results"


@dataclass
class QueryResult:
    id: str
    category: str
    query: str
    expected: list[str]
    returned: list[str]
    similarities: list[float]
    rank: int | None = None  # rank of the first correct file, if any
    agent_matches: list[str] = field(default_factory=list)
    agent_answer: str = ""
    agent_tool_rounds: int = 0
    agent_tokens: int = 0
    agent_error: str | None = None


def build_index() -> int:
    count = 0
    for folder in CORPUS_DIRS:
        for path in sorted(folder.iterdir()):
            if path.name in SKIP or path.suffix not in (".pdf", ".docx", ".txt"):
                continue
            record = document_service.ingest_upload(path.name, path.read_bytes())
            if record.status != "indexed":
                raise SystemExit(f"Indexing {path.name} failed: {record.error_message}")
            count += 1
    return count


def run_query(item: dict, k: int, with_agent: bool) -> QueryResult:
    matches = search_service.search_files(item["query"], limit=k)
    returned = [m.filename for m in matches]
    rank = next((i for i, name in enumerate(returned, start=1) if name in item["expected"]), None)
    result = QueryResult(
        id=item["id"],
        category=item["category"],
        query=item["query"],
        expected=item["expected"],
        returned=returned,
        similarities=[round(m.similarity, 3) for m in matches],
        rank=rank,
    )
    if with_agent:
        try:
            agent = agent_service.run_search_agent(item["query"])
            result.agent_matches = [m.filename for m in agent.matches]
            result.agent_answer = agent.answer
            result.agent_tool_rounds = agent.tool_rounds
            result.agent_tokens = agent.input_tokens + agent.output_tokens
        except AgentError as exc:
            result.agent_error = str(exc)
    return result


def _pct(values: list[float]) -> str:
    return f"{100 * sum(values) / len(values):5.1f}%" if values else "    –"


def summarise(results: list[QueryResult], k: int, with_agent: bool) -> dict:
    answerable = [r for r in results if r.expected]
    no_match = [r for r in results if not r.expected]

    def retrieval(rows: list[QueryResult]) -> dict:
        return {
            "queries": len(rows),
            f"recall@{k}": [1.0 if r.rank else 0.0 for r in rows],
            "hit@1": [1.0 if r.rank == 1 else 0.0 for r in rows],
            "mrr": [1 / r.rank if r.rank else 0.0 for r in rows],
        }

    print(f"\nRetrieval ({settings.search_mode} search, top {k})")
    print(f"  {'category':<11} {'n':>3}  {'Recall@' + str(k):>9}  {'Hit@1':>7}  {'MRR':>6}")
    categories = sorted({r.category for r in answerable}, key=[r.category for r in results].index)
    summary: dict = {"retrieval": {}}
    for name, rows in [*[(c, [r for r in answerable if r.category == c]) for c in categories], ("ALL", answerable)]:
        stats = retrieval(rows)
        mrr = sum(stats["mrr"]) / len(rows)
        print(
            f"  {name:<11} {len(rows):>3}  {_pct(stats[f'recall@{k}']):>9}  {_pct(stats['hit@1']):>7}  {mrr:6.3f}"
        )
        summary["retrieval"][name] = {
            "queries": len(rows),
            f"recall@{k}": sum(stats[f"recall@{k}"]) / len(rows),
            "hit@1": sum(stats["hit@1"]) / len(rows),
            "mrr": mrr,
        }

    correct_top = [r.similarities[0] for r in answerable if r.rank == 1]
    nomatch_top = [r.similarities[0] if r.similarities else 0.0 for r in no_match]
    if correct_top and nomatch_top:
        print(
            f"\n  Top similarity when the first result is correct: "
            f"{min(correct_top):.3f}–{max(correct_top):.3f}"
        )
        print(f"  Top similarity for no_match queries:              {min(nomatch_top):.3f}–{max(nomatch_top):.3f}")
        print("  (Overlap here is why vector search alone can't decide 'no match'; Claude does.)")

    if with_agent:
        ran = [r for r in results if r.agent_error is None]
        hits = [1.0 if set(r.agent_matches) & set(r.expected) else 0.0 for r in ran if r.expected]
        precision = [
            len(set(r.agent_matches) & set(r.expected)) / len(r.agent_matches)
            for r in ran if r.expected and r.agent_matches
        ]
        empty_ok = [1.0 if not r.agent_matches else 0.0 for r in ran if not r.expected]
        tokens = sum(r.agent_tokens for r in ran)
        print("\nAgent (Claude with search_files / inspect_file)")
        print(f"  Recall (correct file named): {_pct(hits)}  over {len(hits)} queries")
        print(f"  Precision of named files:    {_pct(precision)}")
        print(f"  No-match handled correctly:  {_pct(empty_ok)}  over {len(empty_ok)} queries")
        print(f"  Errors: {len(results) - len(ran)}   Tokens used: {tokens:,}")
        summary["agent"] = {
            "recall": sum(hits) / len(hits) if hits else None,
            "precision": sum(precision) / len(precision) if precision else None,
            "no_match_accuracy": sum(empty_ok) / len(empty_ok) if empty_ok else None,
            "errors": len(results) - len(ran),
            "tokens": tokens,
        }
    return summary


def print_row(r: QueryResult, k: int, with_agent: bool) -> None:
    if r.expected:
        mark = "✓" if r.rank else "✗"
        where = f"rank {r.rank}" if r.rank else f"not in top {k}"
    else:
        mark, where = "·", f"top sim {r.similarities[0]:.3f}" if r.similarities else "no results"
    line = f"  {mark} {r.id} [{r.category}] {r.query!r}: {where}"
    if r.expected and r.rank != 1:
        line += f"  (got: {', '.join(f'{n} {s}' for n, s in zip(r.returned[:3], r.similarities))})"
    print(line)
    if with_agent:
        if r.agent_error:
            print(f"      agent ERROR: {r.agent_error}")
        else:
            ok = (bool(set(r.agent_matches) & set(r.expected)) if r.expected else not r.agent_matches)
            extra = [m for m in r.agent_matches if m not in r.expected]
            print(
                f"      agent {'✓' if ok else '✗'} named {r.agent_matches or 'nothing'}"
                + (f"  (extra: {extra})" if extra and r.expected else "")
                + f"  · {r.agent_tool_rounds} round(s)"
            )


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.WARNING)
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--agent", action="store_true", help="also run the Claude agent (costs more)")
    parser.add_argument("--k", type=int, default=5, help="how many files retrieval returns (default 5)")
    parser.add_argument("--only", help="comma-separated query ids, e.g. q25,q30")
    parser.add_argument("--mode", choices=["hybrid", "vector"], default=settings.search_mode)
    args = parser.parse_args()
    settings.search_mode = args.mode

    if not settings.openai_api_key or (args.agent and not settings.anthropic_api_key):
        print("Missing API key(s) in backend/.env.")
        return 2

    dataset = json.loads((EVAL_DIR / "dataset.json").read_text(encoding="utf-8"))["queries"]
    if args.only:
        wanted = set(args.only.split(","))
        dataset = [q for q in dataset if q["id"] in wanted]

    with tempfile.TemporaryDirectory(prefix="filemind-eval-", ignore_cleanup_errors=True) as tmp:
        settings.data_dir = Path(tmp)
        settings.ensure_data_dirs()
        init_db()

        started = time.perf_counter()
        print(f"Indexing eval corpus with {settings.embedding_model}...")
        print(f"  {build_index()} documents indexed in {time.perf_counter() - started:.1f}s")

        print(f"\nRunning {len(dataset)} queries, {args.mode} search" + (", with Claude agent" if args.agent else ""))
        results = []
        for item in dataset:
            result = run_query(item, args.k, args.agent)
            print_row(result, args.k, args.agent)
            results.append(result)

    summary = summarise(results, args.k, args.agent)

    RESULTS_DIR.mkdir(exist_ok=True)
    kind = "agent" if args.agent else "retrieval"
    out = RESULTS_DIR / f"{kind}_{args.mode}_{datetime.now():%Y%m%d_%H%M%S}.json"
    out.write_text(
        json.dumps(
            {
                "settings": {
                    "embedding_model": settings.embedding_model,
                    "chunk_size_tokens": settings.chunk_size_tokens,
                    "chunk_overlap_tokens": settings.chunk_overlap_tokens,
                    "search_max_distance": settings.search_max_distance,
                    "search_mode": settings.search_mode,
                    "k": args.k,
                    "agent_model": settings.anthropic_model if args.agent else None,
                },
                "summary": summary,
                "results": [asdict(r) for r in results],
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"\nSaved {out.relative_to(BACKEND_DIR)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
