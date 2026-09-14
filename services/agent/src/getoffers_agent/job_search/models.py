"""Pinned BGE adapters. Tests inject deterministic vectors, never impersonate BGE."""

from typing import Protocol

import numpy as np

from getoffers_agent.domain.contracts import digest

BGE_REVISION = "5617a9f61b028005a4858fdac845db406aefb181"
RERANKER_REVISION = "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"


class DenseEncoder(Protocol):
    identity: str
    dimension: int

    def encode(self, texts: list[str]) -> list[list[float]]: ...


class Reranker(Protocol):
    identity: str

    def score(self, query: str, documents: list[str]) -> list[float]: ...


class BGEEncoder:
    dimension = 1024

    def __init__(self, cache_dir: str, *, device: str = "cpu", max_length: int = 1024):
        from sentence_transformers import SentenceTransformer

        self.identity = digest(
            {
                "name": "BAAI/bge-m3",
                "revision": BGE_REVISION,
                "max_length": max_length,
                "normalize": True,
                "device": device,
            }
        )
        self.model = SentenceTransformer(
            "BAAI/bge-m3",
            revision=BGE_REVISION,
            cache_folder=cache_dir,
            device=device,
            trust_remote_code=False,
            local_files_only=True,
        )
        self.model.max_seq_length = max_length

    def encode(self, texts: list[str]) -> list[list[float]]:
        vectors = self.model.encode(
            texts, batch_size=4, normalize_embeddings=True, show_progress_bar=False
        )
        return np.asarray(vectors, dtype=float).tolist()


class BGEReranker:
    def __init__(self, cache_dir: str, *, device: str = "cpu", max_length: int = 1024):
        from sentence_transformers import CrossEncoder

        self.identity = digest(
            {
                "name": "BAAI/bge-reranker-v2-m3",
                "revision": RERANKER_REVISION,
                "max_length": max_length,
                "activation": "sigmoid",
                "device": device,
            }
        )
        self.model = CrossEncoder(
            "BAAI/bge-reranker-v2-m3",
            revision=RERANKER_REVISION,
            cache_folder=cache_dir,
            device=device,
            max_length=max_length,
            trust_remote_code=False,
            local_files_only=True,
        )

    def score(self, query: str, documents: list[str]) -> list[float]:
        import torch

        values = self.model.predict(
            [(query, document) for document in documents],
            batch_size=4,
            show_progress_bar=False,
            activation_fn=torch.nn.Sigmoid(),
        )
        return np.asarray(values, dtype=float).reshape(-1).tolist()
