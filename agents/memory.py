"""
Agent memory — stores context and past decisions for learning.
Uses TF-IDF similarity for memory retrieval.
"""
import json
import logging
from typing import List, Optional
from core.database import Database

logger = logging.getLogger(__name__)

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False


class AgentMemory:
    """Simple memory system for agents using TF-IDF similarity retrieval."""

    def __init__(self, db: Database):
        self.db = db

    async def store(self, agent_name: str, key: str, value: str):
        """Store a memory item."""
        await self.db.store_memory(agent_name, key, value)
        logger.debug(f"Stored memory for {agent_name}: {key[:50]}")

    async def recall(self, agent_name: str, query: str, top_k: int = 5) -> List[dict]:
        """Recall relevant memories using TF-IDF similarity."""
        memories = await self.db.get_memories(agent_name, limit=100)

        if not memories or not HAS_SKLEARN:
            return memories[:top_k]

        # Build corpus from memory values
        texts = [m.get("memory_value", "") for m in memories]
        texts.append(query)

        try:
            vectorizer = TfidfVectorizer(max_features=1000, stop_words='english')
            tfidf_matrix = vectorizer.fit_transform(texts)

            # Compute similarity of query vs all memories
            query_vector = tfidf_matrix[-1]
            memory_vectors = tfidf_matrix[:-1]
            similarities = cosine_similarity(query_vector, memory_vectors)[0]

            # Rank by similarity
            ranked = sorted(enumerate(similarities), key=lambda x: x[1], reverse=True)
            results = []
            for idx, score in ranked[:top_k]:
                memory = memories[idx].copy()
                memory["relevance_score"] = float(score)
                results.append(memory)

            return results
        except Exception as e:
            logger.error(f"Memory recall failed: {e}")
            return memories[:top_k]

    async def summarize_context(self, agent_name: str, query: str) -> str:
        """Build a context string from relevant memories."""
        memories = await self.recall(agent_name, query)
        if not memories:
            return "No prior context available."

        lines = ["Prior context:"]
        for m in memories:
            key = m.get("memory_key", "")
            value = m.get("memory_value", "")
            score = m.get("relevance_score", 0)
            lines.append(f"- [{score:.2f}] {key}: {value[:200]}")

        return "\n".join(lines)
