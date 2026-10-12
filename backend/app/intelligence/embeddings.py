import json
import math
import urllib.error
import urllib.request
from typing import Protocol

from app.config import get_settings

DIMENSIONS = 1536
BATCH_SIZE = 32
MAX_RESPONSE_BYTES = 4 * 1024 * 1024


class EmbeddingError(Exception):
    """Safe public failure message; never include provider bodies, keys, or inputs."""


class EmbeddingProvider(Protocol):
    model_id: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def validate_vectors(vectors: list, expected_count: int) -> list[list[float]]:
    if not isinstance(vectors, list) or len(vectors) != expected_count:
        raise EmbeddingError("Embedding provider returned an incorrect number of vectors")
    normalized = []
    for vector in vectors:
        if not isinstance(vector, list) or len(vector) != DIMENSIONS:
            raise EmbeddingError("Embedding provider returned incompatible vector dimensions")
        if any(type(value) not in (int, float) or not math.isfinite(value) for value in vector):
            raise EmbeddingError("Embedding provider returned invalid vector values")
        magnitude = math.hypot(*vector)
        if not math.isfinite(magnitude) or magnitude == 0:
            raise EmbeddingError("Embedding provider returned a zero or invalid vector")
        # Unit vectors keep cosine calculations safe in pgvector's float32 storage.
        normalized.append([float(value) / magnitude for value in vector])
    return normalized


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class OpenAIEmbeddingProvider:
    def __init__(self, api_key: str, model: str, timeout: float = 30):
        self._api_key = api_key
        self.model = model
        self.model_id = f"openai:{model}:{DIMENSIONS}"
        self.timeout = timeout

    def _request(self, texts: list[str]) -> dict:
        request = urllib.request.Request(
            "https://api.openai.com/v1/embeddings",
            data=json.dumps({"model": self.model, "input": texts,
                             "dimensions": DIMENSIONS, "encoding_format": "float"}).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self._api_key}"},
            method="POST",
        )
        try:
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=self.timeout) as response:
                content = response.read(MAX_RESPONSE_BYTES + 1)
            if len(content) > MAX_RESPONSE_BYTES:
                raise EmbeddingError("Embedding provider response exceeded the size limit")
            return json.loads(content)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            raise EmbeddingError("Embedding provider is unavailable or returned an invalid response") from None

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts or any(not text.strip() or len(text) > 1200 for text in texts):
            raise EmbeddingError("Embedding inputs must contain between 1 and 1200 characters")
        vectors = []
        for start in range(0, len(texts), BATCH_SIZE):
            batch = texts[start:start + BATCH_SIZE]
            payload = self._request(batch)
            try:
                if payload["model"] != self.model or len(payload["data"]) != len(batch):
                    raise ValueError()
                if any(type(item["index"]) is not int for item in payload["data"]):
                    raise ValueError()
                items = sorted(payload["data"], key=lambda item: item["index"])
                if [item["index"] for item in items] != list(range(len(batch))):
                    raise ValueError()
                vectors.extend(validate_vectors([item["embedding"] for item in items], len(batch)))
            except (KeyError, TypeError, ValueError):
                raise EmbeddingError("Embedding provider returned an incompatible response") from None
        return vectors


def get_embedding_provider() -> EmbeddingProvider | None:
    settings = get_settings()
    if settings.embedding_provider == "disabled":
        return None
    return OpenAIEmbeddingProvider(settings.openai_api_key.get_secret_value(), settings.embedding_model,
                                   settings.embedding_timeout_seconds)
