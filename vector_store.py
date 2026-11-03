import numpy as np
import faiss
from sentence_transformers import CrossEncoder
from typing import List
from config import client, EMBED_MODEL, DIMS, RERANKER_MODEL, logger, record_usage

# -----------------------------
# RERANKER
# -----------------------------
# Load reranker (takes time) - consider lazy loading for production
logger.info("Loading cross-encoder reranker...")
RERANKER = CrossEncoder(RERANKER_MODEL)
logger.info("Reranker loaded.")

# -----------------------------
# EMBEDDING + FAISS HELPERS
# -----------------------------
def create_embeddings(text_chunks: List[str], batch_size: int = 8) -> np.ndarray:
    embeddings = []
    text_chunks = [str(t) for t in text_chunks]
    for i in range(0, len(text_chunks), batch_size):
        batch = text_chunks[i:i + batch_size]
        try:
            resp = client.embeddings.create(model=EMBED_MODEL, input=batch)
            record_usage(EMBED_MODEL, resp.usage)
            for itm in resp.data:
                vec = np.array(itm.embedding, dtype=np.float32)
                embeddings.append(vec)
        except Exception as e:
            logger.exception("Embedding batch failed: %s. Retrying individually.", e)
            for txt in batch:
                try:
                    r = client.embeddings.create(model=EMBED_MODEL, input=[txt])
                    record_usage(EMBED_MODEL, r.usage)
                    vec = np.array(r.data[0].embedding, dtype=np.float32)
                    embeddings.append(vec)
                except Exception as e2:
                    logger.exception("Failed to embed text: %s", e2)
                    embeddings.append(np.zeros(DIMS, dtype=np.float32))

    if not embeddings:
        return np.zeros((0, DIMS), dtype=np.float32)
    return np.vstack(embeddings)

def build_faiss_index(emb: np.ndarray) -> faiss.IndexFlatIP:
    if emb.size == 0:
        idx = faiss.IndexFlatIP(DIMS)
        return idx
    faiss.normalize_L2(emb)
    idx = faiss.IndexFlatIP(DIMS)
    idx.add(emb)
    return idx

