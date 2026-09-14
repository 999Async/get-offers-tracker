"""Reproducible local ingestion, indexing, search and paired evaluation commands."""

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

from qdrant_client import QdrantClient

from getoffers_agent.cli import write_report
from getoffers_agent.domain.contracts import SecurityContext
from getoffers_agent.job_search.contracts import (
    HardConstraints,
    JobInput,
    SearchConfig,
    SearchRequest,
    now,
)
from getoffers_agent.job_search.evaluation import SearchDataset, evaluate_search
from getoffers_agent.job_search.index import QdrantJobIndex
from getoffers_agent.job_search.ingestion import from_greenhouse, from_legacy_feed
from getoffers_agent.job_search.models import BGEEncoder, BGEReranker
from getoffers_agent.job_search.search import JobSearch
from getoffers_agent.job_search.store import JobFactStore


def local_identity():
    return SecurityContext(
        actor_id="local-search-user",
        tenant_id="local-search-user",
        capabilities=frozenset({"job:ingest", "job:ingest:shared", "job:search"}),
    )


def main():
    parser = argparse.ArgumentParser(description="Versioned whole-job search")
    parser.add_argument("--data-dir", type=Path, default=Path(".agent-data/search"))
    parser.add_argument(
        "--qdrant-url", help="Optional running Qdrant server; otherwise local storage"
    )
    parser.add_argument("--models", type=Path, default=Path(".agent-data/models"))
    parser.add_argument("--device", choices=["cpu", "mps", "cuda"], default="cpu")
    parser.add_argument("--max-length", type=int, default=1024)
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("ingest")
    ingest.add_argument("source", type=Path)
    ingest.add_argument("--format", choices=["jobs", "legacy-feed", "greenhouse"], default="jobs")
    ingest.add_argument("--board", default="figureai")
    ingest.add_argument("--company", default="Figure AI")
    ingest.add_argument("--observed-at", default=None)
    build = commands.add_parser("build")
    build.add_argument("--neural", action="store_true")
    build.add_argument(
        "--source-kind", choices=["synthetic", "public-official", "imported"], default="imported"
    )
    search = commands.add_parser("search")
    search.add_argument("query")
    search.add_argument(
        "--mode", choices=["lexical", "dense", "hybrid", "hybrid-rerank"], default="lexical"
    )
    search.add_argument("--city", action="append", default=[])
    search.add_argument("--exclude", action="append", default=[])
    search.add_argument("--top-k", type=int, default=10)
    activate = commands.add_parser("activate")
    activate.add_argument("index_id")
    commands.add_parser("repair-alias")
    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("dataset", type=Path)
    evaluate.add_argument("--neural", action="store_true")
    evaluate.add_argument("--candidate-limit", type=int, default=100)
    evaluate.add_argument("--out", type=Path, required=True)
    serve = commands.add_parser("serve")
    serve.add_argument("--port", type=int, default=8766)
    serve.add_argument(
        "--mode", choices=["lexical", "dense", "hybrid", "hybrid-rerank"], default="lexical"
    )
    args = parser.parse_args()
    client = None
    try:
        args.data_dir.mkdir(parents=True, exist_ok=True)
        facts = JobFactStore(args.data_dir / "facts.sqlite")
        if args.command == "ingest":
            raw = args.source.read_bytes()
            stamp = datetime.fromisoformat(args.observed_at) if args.observed_at else now()
            if args.format == "greenhouse":
                jobs = from_greenhouse(raw, args.board, args.company, stamp)
            elif args.format == "legacy-feed":
                jobs = from_legacy_feed(raw, stamp)
            else:
                data = json.loads(raw)
                rows = data["jobs"] if isinstance(data, dict) else data
                jobs = [JobInput.model_validate(row) for row in rows]
            print(json.dumps(facts.ingest(jobs, local_identity()), indent=2))
            return
        client = (
            QdrantClient(url=args.qdrant_url, timeout=30)
            if args.qdrant_url
            else QdrantClient(
                path=str(args.data_dir / "qdrant"), force_disable_check_same_thread=True
            )
        )
        index = QdrantJobIndex(client, facts)
        neural = getattr(args, "neural", False) or getattr(args, "mode", "lexical") != "lexical"
        encoder = (
            BGEEncoder(str(args.models), device=args.device, max_length=args.max_length)
            if neural
            else None
        )
        reranker = (
            BGEReranker(str(args.models), device=args.device, max_length=args.max_length)
            if (
                args.command == "evaluate"
                and neural
                or getattr(args, "mode", None) == "hybrid-rerank"
            )
            else None
        )
        if args.command == "build":
            manifest = index.build(facts.snapshot(args.source_kind), SearchConfig(), encoder)
            repaired = index.activate(manifest["index_id"])
            print(
                json.dumps(
                    {
                        "index_id": manifest["index_id"],
                        "jobs": len(manifest["version_ids"]),
                        "alias_synchronized": repaired,
                        "build_ms": manifest["build_duration_ms"],
                    },
                    indent=2,
                )
            )
        elif args.command == "search":
            result = JobSearch(index, SearchConfig(mode=args.mode), encoder, reranker).search(
                SearchRequest(
                    query=args.query,
                    top_k=args.top_k,
                    hard_constraints=HardConstraints(
                        cities=tuple(args.city), excluded_terms=tuple(args.exclude)
                    ),
                ),
                local_identity(),
            )
            print(result.model_dump_json(indent=2))
        elif args.command == "activate":
            print(
                json.dumps(
                    {"index_id": args.index_id, "alias_synchronized": index.activate(args.index_id)}
                )
            )
        elif args.command == "repair-alias":
            print(json.dumps({"alias_synchronized": index.reconcile_alias()}))
        elif args.command == "serve":
            from getoffers_agent.job_search.server import serve_search

            token = os.environ.get("AGENT_SEARCH_TOKEN", "")
            serve_search(
                JobSearch(index, SearchConfig(mode=args.mode), encoder, reranker),
                token=token,
                port=args.port,
            )
        elif args.command == "evaluate":
            dataset = SearchDataset.model_validate_json(args.dataset.read_text())
            modes = ["lexical", "dense", "hybrid", "hybrid-rerank"] if neural else ["lexical"]
            configs = [
                SearchConfig(mode=mode, candidate_limit=args.candidate_limit) for mode in modes
            ]
            report = evaluate_search(index, dataset, configs, local_identity(), encoder, reranker)
            write_report(args.out, report)
            print(
                json.dumps(
                    {
                        "report": str(args.out.resolve()),
                        "cases": len(dataset.cases),
                        "gate": report["gate"],
                    },
                    indent=2,
                )
            )
            if not report["gate"]["safety_passed"]:
                raise SystemExit(1)
    except (ValueError, PermissionError, OSError) as exc:
        parser.exit(2, f"job_search_error:{type(exc).__name__}\n")
    finally:
        if client:
            client.close()


if __name__ == "__main__":
    main()
