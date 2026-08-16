"""
pipeline/retrieve.py — embeds a query and retrieves top-k chunks from
Chroma Cloud. Works against all 3 indexed strategies (fixed / semantic /
metadata) so we can compare them, or pick one as the default for generation.

IMPORTANT: must use the exact same embedding model + query prefix convention
("query: ...") that built the index (intfloat/multilingual-e5-small), or
similarity scores are meaningless - see indexing notebook Cell A.
"""

import os
from dataclasses import dataclass
from dotenv import load_dotenv
import chromadb
from sentence_transformers import SentenceTransformer

load_dotenv()

CHROMA_API_KEY = os.getenv("CHROMA_API_KEY")
if not CHROMA_API_KEY:
    raise RuntimeError("CHROMA_API_KEY not found - check your .env file")

EMBED_MODEL_NAME = "intfloat/multilingual-e5-small"   # MUST match indexing notebook

COLLECTION_NAMES = {
    "fixed": "rag_chunks_fixed",
    "semantic": "rag_chunks_semantic",
    "metadata": "rag_chunks_metadata",
}

_chroma_client = chromadb.CloudClient(api_key=CHROMA_API_KEY)
_embed_model = SentenceTransformer(EMBED_MODEL_NAME)   # loaded once, reused across calls


@dataclass
class RetrievedChunk:
    text: str
    metadata: dict
    similarity: float          # 0..1, higher = more relevant (converted from Chroma's distance)
    strategy: str


def _embed_query(query_text: str):
    # normalize_embeddings=True -> vectors are unit length, so cosine similarity
    # can be computed cheaply as (1 - squared_l2_distance / 2) below
    return _embed_model.encode(["query: " + query_text], normalize_embeddings=True)[0].tolist()


def retrieve(query_text: str, strategy: str = "metadata", top_k: int = 5) -> list[RetrievedChunk]:
    """
    strategy: "fixed" | "semantic" | "metadata" — which chunking strategy's
    collection to search. Default "metadata" since it preserves the cleanest
    passage-level units with is_selected ground-truth for eval later.
    """
    if strategy not in COLLECTION_NAMES:
        raise ValueError(f"strategy must be one of {list(COLLECTION_NAMES)}, got {strategy!r}")

    collection = _chroma_client.get_or_create_collection(COLLECTION_NAMES[strategy])
    query_embedding = _embed_query(query_text)

    result = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )

    chunks = []
    docs = result["documents"][0]
    metas = result["metadatas"][0]
    distances = result["distances"][0]   # Chroma default: squared L2 on normalized vectors

    for text, meta, dist in zip(docs, metas, distances):
        # for unit-normalized vectors, squared L2 distance relates to cosine
        # similarity as: cos_sim = 1 - (dist / 2). Clamp for float noise.
        similarity = max(0.0, min(1.0, 1 - (dist / 2)))
        chunks.append(RetrievedChunk(text=text, metadata=meta, similarity=similarity, strategy=strategy))

    return chunks


def retrieve_all_strategies(query_text: str, top_k: int = 3) -> dict[str, list[RetrievedChunk]]:
    """Convenience: run the same query against all 3 collections, for
    comparison/debugging. Not what generation will use - generation picks
    one strategy (see pipeline/generate.py, next)."""
    return {name: retrieve(query_text, strategy=name, top_k=top_k) for name in COLLECTION_NAMES}


if __name__ == "__main__":
    import sys

    # Usage:
    #   python retrieve.py "your question here"
    #   python retrieve.py --audio test_audio.mp3   (chains STT -> retrieval)
    if len(sys.argv) > 1 and sys.argv[1] == "--audio":
        from stt import transcribe   # only import when needed - avoids requiring Sarvam key for text-only tests
        audio_path = sys.argv[2]
        stt_result = transcribe(audio_path)
        print(f"Transcript: {stt_result.transcript!r}  (lang: {stt_result.language_code})")
        query = stt_result.transcript
    else:
        query = " ".join(sys.argv[1:]) or "what is the capital of india"
        print(f"Query: {query!r}")

    for strategy_name, chunks in retrieve_all_strategies(query, top_k=3).items():
        print(f"\n--- {strategy_name} ---")
        for c in chunks:
            print(f"  [{c.similarity:.3f}] {c.text[:120]}...")