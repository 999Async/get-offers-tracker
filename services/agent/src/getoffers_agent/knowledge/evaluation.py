"""Frozen synthetic parsing/retrieval baseline; never a human-reviewed release gate."""

import hashlib
import json
import platform
import resource
import tempfile
from pathlib import Path
from statistics import mean
from time import perf_counter

from qdrant_client import QdrantClient

from getoffers_agent.domain.contracts import SecurityContext, digest
from getoffers_agent.job_search.evaluation import retrieval_metrics
from getoffers_agent.knowledge.contracts import EvidenceQuery, KnowledgeConfig
from getoffers_agent.knowledge.index import EvidenceIndex
from getoffers_agent.knowledge.parsing import DocumentParser
from getoffers_agent.knowledge.service import KnowledgeService
from getoffers_agent.knowledge.store import KnowledgeStore, LocalArtifacts


def evaluate(dataset_path, output, *, neural=False, models_path=".agent-data/models", device="cpu"):
    data = json.loads(dataset_path.read_text())
    encoder = reranker = None
    if neural:
        from getoffers_agent.job_search.models import BGEEncoder, BGEReranker

        encoder = BGEEncoder(models_path, device=device, max_length=512)
        reranker = BGEReranker(models_path, device=device, max_length=512)
    security = SecurityContext(
        actor_id="synthetic-evaluator",
        tenant_id="synthetic-evaluator",
        capabilities=frozenset(
            {"knowledge:upload:self", "knowledge:read:self", "knowledge:delete:self"}
        ),
    )
    config = KnowledgeConfig()
    with tempfile.TemporaryDirectory(prefix="getoffers-knowledge-eval-") as directory:
        store = KnowledgeStore(Path(directory) / "facts.sqlite")
        client = QdrantClient(":memory:")
        try:
            service = KnowledgeService(
                store,
                LocalArtifacts(Path(directory) / "artifacts"),
                EvidenceIndex(client, store, encoder, reranker),
                config,
            )
            documents, parsing = {}, []
            for item in data["documents"]:
                raw = item["content"].encode()
                started = perf_counter()
                canonical = DocumentParser(config).parse(raw, item["format"])
                assert [n.kind for n in canonical.nodes] == item["expected_kinds"]
                for quote in item["preserved_quotes"]:
                    assert any(quote in n.text for n in canonical.nodes)
                second = DocumentParser(config).parse(raw, item["format"])
                assert canonical == second
                parsing.append(
                    {
                        "id": item["id"],
                        "source_sha256": hashlib.sha256(raw).hexdigest(),
                        "node_count": len(canonical.nodes),
                        "deterministic": True,
                        "preserved_quotes": True,
                        "locator_coverage": mean(bool(n.locator) for n in canonical.nodes),
                        "duration_ms": (perf_counter() - started) * 1000,
                    }
                )
                # Stable document IDs make Evidence IDs reproducible across executions.
                stable_id = digest([data["version"], item["id"]])
                with store.connect() as db:
                    db.execute(
                        "INSERT INTO knowledge_documents VALUES(?,?,?,?,?,?)",
                        (
                            stable_id,
                            security.tenant_id,
                            item["id"],
                            "uploaded",
                            None,
                            "2026-09-06T00:00:00+00:00",
                        ),
                    )
                doc = service.upload(
                    item["id"] + "." + item["format"],
                    "text/markdown" if item["format"] == "md" else "text/plain",
                    raw,
                    security,
                    stable_id,
                )
                service.process(**doc, security=security)
                documents[item["id"]] = doc["document_id"]
            units = service.active_units(security.tenant_id)
            reports = []
            for mode in ["lexical", "dense", "hybrid", "hybrid-rerank"] if neural else ["lexical"]:
                cases = []
                for case in data["queries"]:
                    expected = [
                        u.evidence_id
                        for u in units
                        if u.document_id == documents[case["document"]]
                        and case["expected_quote"] in u.text
                    ]
                    if not expected:
                        raise ValueError("gold_quote_not_in_evidence")
                    result = service.retrieve(
                        EvidenceQuery(
                            query=case["query"],
                            document_ids=tuple(documents.values()),
                            mode=mode,
                            top_k=10,
                            token_budget=16000,
                        ),
                        security,
                    )
                    ids = [r["evidence_id"] for r in result["evidence"]]
                    cases.append(
                        {
                            "case_id": case["id"],
                            "ranked_evidence_ids": ids,
                            "expected_evidence_ids": expected,
                            "metrics": retrieval_metrics(ids, {k: 3 for k in expected}),
                            "citation_valid": all(service.citation(k, security) for k in ids),
                            "duration_ms": result["duration_ms"],
                            "config_hash": result["config_hash"],
                        }
                    )
                latencies = sorted(c["duration_ms"] for c in cases)
                reports.append(
                    {
                        "mode": mode,
                        "cases": cases,
                        "metrics": {
                            k: mean(c["metrics"][k] for c in cases) for k in cases[0]["metrics"]
                        },
                        "p50_ms": latencies[len(latencies) // 2],
                        "p95_ms": latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))],
                    }
                )
            report = {
                "schema_version": 1,
                "dataset_version": data["version"],
                "dataset_hash": digest(data),
                "source_kind": "synthetic",
                "document_count": len(parsing),
                "query_count": len(data["queries"]),
                "parsing": parsing,
                "reports": reports,
                "config": config.model_dump(mode="json"),
                "encoder_identity": encoder.identity if encoder else "none",
                "reranker_identity": reranker.identity if reranker else "none",
                "code_hash": digest(
                    {p.name: p.read_text() for p in sorted(Path(__file__).parent.glob("*.py"))}
                ),
                "dependency_lock_hash": hashlib.sha256(
                    (Path(__file__).parents[3] / "uv.lock").read_bytes()
                ).hexdigest(),
                "environment": {
                    "python": platform.python_version(),
                    "system": platform.system(),
                    "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                    * (1 if platform.system() == "Darwin" else 1024),
                },
                "gate": {
                    "engineering_checks_passed": True,
                    "human_reviewed_cases": 0,
                    "reviewed_dataset_ready": False,
                    "production_release_ready": False,
                },
                "limits": [
                    "Synthetic Markdown/TXT corpus; not reviewed real resumes or Parsing Gold.",
                    "PDF/DOCX require separate adapter integration checks.",
                    "No production performance or answer-faithfulness claim.",
                ],
            }
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
            print(
                json.dumps(
                    {
                        "report": str(output),
                        "documents": len(parsing),
                        "queries": len(data["queries"]),
                        "gate": report["gate"],
                    }
                )
            )
            return report
        finally:
            client.close()
