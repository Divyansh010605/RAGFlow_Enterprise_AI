"""Production service adapters with graceful local fallback for offline development."""
import logging
from hashlib import sha256
from typing import Any
from .config import GEMINI_API_KEY, GEMINI_MODEL, NEO4J_PASSWORD, NEO4J_URI, QDRANT_URL, REDIS_URL

logger = logging.getLogger(__name__)

class RedisCache:
    def __init__(self, max_local: int = 500):
        self.local: dict[str, Any] = {}
        self.max_local = max_local
        self.client = None
        if REDIS_URL:
            try:
                import redis; self.client = redis.from_url(REDIS_URL, decode_responses=True); self.client.ping()
            except Exception as exc:
                logger.warning("Redis unavailable, falling back to in-process cache: %s", exc)
                self.client = None
    def get(self, key):
        if self.client:
            try:
                import json; value=self.client.get(key); return json.loads(value) if value else None
            except Exception: pass
        return self.local.get(key)
    def put(self, key, value, ttl=900):
        if self.client:
            try:
                import json; self.client.setex(key, ttl, json.dumps(value)); return
            except Exception: pass
        if len(self.local) >= self.max_local:
            oldest = next(iter(self.local), None)
            if oldest: del self.local[oldest]
        self.local[key] = value

cache = RedisCache()

def answer_with_llm(question: str, evidence: list[dict], custom_system_prompt: str | None = None) -> str | None:
    """Grounded completion with automatic model fallback."""
    if not GEMINI_API_KEY or not evidence: return None
    context="\n\n".join(f"[{item.get('filename', item.get('source','source'))}]\n{item['text'][:1200]}" for item in evidence[:6])
    
    system_instruction = custom_system_prompt or (
        "You are RAGFlow Enterprise AI assistant. "
        "Read the provided evidence context and answer the user's question directly, clearly, and concisely in well-structured markdown. "
        "Synthesize and summarize the key facts to directly answer what was asked. "
        "Do NOT copy-paste raw chunk dumps or verbatim long passages from the evidence. "
        "If the evidence does not contain the answer, state clearly what information is available and what is missing. "
        "Always mention the source document names when stating facts."
    )

    models_to_try = [GEMINI_MODEL, "gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro"]
    models_to_try = list(dict.fromkeys([m for m in models_to_try if m]))

    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=GEMINI_API_KEY)

        for model_name in models_to_try:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=f"User Question: {question}\n\nEvidence Context:\n{context}",
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        temperature=0.2,
                    ),
                )
                if response.text:
                    return response.text
            except Exception as exc:
                logger.warning("LLM model '%s' failed (%s: %s). Trying fallback...", model_name, type(exc).__name__, exc)
    except Exception as exc:
        logger.error("LLM initialization failed (%s: %s) — falling back to keyword extraction.", type(exc).__name__, exc)

    return None

_neo4j_driver = None

def get_neo4j_driver():
    global _neo4j_driver
    if _neo4j_driver is None and NEO4J_URI:
        try:
            from neo4j import GraphDatabase
            _neo4j_driver = GraphDatabase.driver(NEO4J_URI, auth=("neo4j", NEO4J_PASSWORD))
        except Exception as exc:
            logger.warning("Unable to initialize Neo4j driver: %s", exc)
            _neo4j_driver = None
    return _neo4j_driver

def cypher_read(query: str, parameters: dict | None = None) -> list[dict]:
    if not NEO4J_URI: return []
    normalized=" ".join(query.split()).lower()
    if not normalized.startswith("match") or any(word in normalized for word in ("create","merge","delete","set","drop","call")):
        raise ValueError("Only read-only MATCH Cypher queries are allowed")
    try:
        driver = get_neo4j_driver()
        if not driver: return []
        with driver.session() as session:
            return [record.data() for record in session.run(query, parameters or {})]
    except Exception as exc:
        logger.warning("Neo4j query failed: %s", exc)
        return []

