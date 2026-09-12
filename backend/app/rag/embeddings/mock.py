"""Mock embedding provider for tests."""

import hashlib
import math
import random

from app.rag.embeddings.base import BaseEmbeddingProvider


class MockEmbeddingProvider(BaseEmbeddingProvider):
    """Deterministic hash-based vectors for verifying pipeline orchestration.

    WARNING: This provider must NOT be treated as a benchmark or proof of
    semantic retrieval quality. It merely provides deterministic unit vectors
    for reliable testing and offline development.
    """

    @property
    def dimension(self) -> int:
        return 1536

    @property
    def model_name(self) -> str:
        return "mock-deterministic-1536"

    def _generate_deterministic_vector(self, text: str) -> list[float]:
        """Generates a deterministic, L2-normalized vector from a text hash."""
        # Use SHA-256 to seed a deterministic random generator for this specific string
        seed_hash = hashlib.sha256(text.encode("utf-8")).digest()
        seed = int.from_bytes(seed_hash[:8], "big")

        # Not used for cryptographic purposes — this only needs to be a fast,
        # deterministic, seed-reproducible generator for test/offline vectors.
        rng = random.Random(seed)  # noqa: S311

        # Generate random vector
        vector = [rng.gauss(0, 1) for _ in range(self.dimension)]

        # L2 Normalize
        norm = math.sqrt(sum(v * v for v in vector))
        if norm > 0:
            vector = [v / norm for v in vector]

        return vector

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._generate_deterministic_vector(text) for text in texts]

    async def embed_query(self, query: str) -> list[float]:
        return self._generate_deterministic_vector(query)
