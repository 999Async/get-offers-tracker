"""Local knowledge service and reproducible evaluation entry points."""

import argparse
import os
from pathlib import Path

from qdrant_client import QdrantClient

from getoffers_agent.knowledge.index import EvidenceIndex
from getoffers_agent.knowledge.server import make_knowledge_server
from getoffers_agent.knowledge.service import KnowledgeService
from getoffers_agent.knowledge.store import KnowledgeStore, LocalArtifacts, R2Artifacts


def main():
    parser = argparse.ArgumentParser(description="Private knowledge service")
    parser.add_argument("--data-dir", type=Path, default=Path(".agent-data/knowledge"))
    parser.add_argument("--qdrant-url")
    parser.add_argument("--neural", action="store_true")
    parser.add_argument("--device", default="cpu", choices=["cpu", "mps", "cuda"])
    parser.add_argument("--models", default=".agent-data/models")
    parser.add_argument("--r2", action="store_true", help="Use configured private R2 bucket")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve")
    serve.add_argument("--port", type=int, default=8767)
    evaluation = commands.add_parser("evaluate")
    evaluation.add_argument(
        "--dataset", type=Path, default=Path("datasets/evals/knowledge-v1/cases.json")
    )
    evaluation.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "evaluate":
        from getoffers_agent.knowledge.evaluation import evaluate

        evaluate(
            args.dataset, args.out, neural=args.neural, models_path=args.models, device=args.device
        )
        return
    args.data_dir.mkdir(parents=True, exist_ok=True)
    store = KnowledgeStore(args.data_dir / "facts.sqlite")
    artifacts = LocalArtifacts(args.data_dir / "artifacts")
    if args.r2:
        import boto3

        artifacts = R2Artifacts(
            boto3.client(
                "s3",
                endpoint_url=os.environ["KNOWLEDGE_R2_ENDPOINT"],
                region_name="auto",
                aws_access_key_id=os.environ["KNOWLEDGE_R2_ACCESS_KEY_ID"],
                aws_secret_access_key=os.environ["KNOWLEDGE_R2_SECRET_ACCESS_KEY"],
            ),
            os.environ["KNOWLEDGE_R2_BUCKET"],
        )
    encoder = reranker = None
    if args.neural:
        from getoffers_agent.job_search.models import BGEEncoder, BGEReranker

        encoder = BGEEncoder(args.models, device=args.device, max_length=512)
        reranker = BGEReranker(args.models, device=args.device, max_length=512)
    client = (
        QdrantClient(url=args.qdrant_url)
        if args.qdrant_url
        else QdrantClient(path=str(args.data_dir / "qdrant"), force_disable_check_same_thread=True)
    )
    try:
        service = KnowledgeService(
            store, artifacts, EvidenceIndex(client, store, encoder, reranker)
        )
        with make_knowledge_server(
            service, os.environ.get("AGENT_KNOWLEDGE_TOKEN", ""), args.port
        ) as server:
            server.serve_forever()
    finally:
        client.close()


if __name__ == "__main__":
    main()
