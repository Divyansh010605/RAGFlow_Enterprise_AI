from .rag import search

def evaluate_retrieval(question: str, user_id: str) -> dict:
    results=search(question,user_id,5)
    score=round(min(1, sum(item["score"] for item in results)/(len(results)*3 or 1)),2)
    return {"question":question,"retrieved":len(results),"context_relevance":score,"answer_relevance":score,"faithfulness":"requires a generated answer and ground truth","ragas_ready":True}
