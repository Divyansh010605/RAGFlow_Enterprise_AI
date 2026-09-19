"""Local retrieval adapter. Replace this module with Qdrant/embedding clients in production."""
from collections import Counter
from math import log, sqrt
import re
from .database import connection

def tokens(text: str) -> list[str]: return re.findall(r"[a-zA-Z0-9_]+", text.lower())
def chunk(text: str, size: int = 900, overlap: int = 120) -> list[str]:
    text = " ".join(text.split())
    if not text:
        return []
    return [text[i:i + size] for i in range(0, len(text), max(1, size - overlap))] or [text]

def search(query: str, user_id: str, limit: int = 5) -> list[dict]:
    terms = tokens(query)
    if not terms: return []
    with connection() as conn:
        rows = conn.execute("""SELECT c.id,c.text,c.ordinal,d.id document_id,d.filename
            FROM chunks c JOIN documents d ON c.document_id=d.id
            WHERE d.user_id=? AND d.status='ready'""", (user_id,)).fetchall()
    docs = [tokens(r["text"]) for r in rows]
    total = len(docs) or 1
    df = Counter(word for words in docs for word in set(words))
    q = Counter(terms)
    scored=[]
    for row, words in zip(rows, docs):
        counts=Counter(words)
        # Only compute TF-IDF score for terms actually present in the document
        bm25=sum((counts[t]/(len(words) or 1))*(log((total+1)/(df[t]+1))+1.0) for t in q if counts[t] > 0)
        dot=sum(q[t]*counts[t] for t in q)
        denom=sqrt(sum(v*v for v in q.values()))*sqrt(sum(v*v for v in counts.values()))
        score=bm25+(dot/denom if denom else 0)
        if score > 0:
            scored.append({"chunk_id":row["id"],"document_id":row["document_id"],"filename":row["filename"],"ordinal":row["ordinal"],"text":row["text"],"score":round(score,3)})
    return sorted(scored,key=lambda x:x["score"],reverse=True)[:limit]

