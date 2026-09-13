from pathlib import Path
from io import BytesIO
from uuid import uuid4
from time import perf_counter
import re
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from .config import CORS_ORIGINS, MAX_UPLOAD_BYTES
from .database import connection, initialize
from .models import ChatRequest, LoginRequest, RegisterRequest, SQLRequest
from .security import audit, current_user, hash_password, token_for, verify_password, validate_read_only_sql
from .rag import chunk, search
from .agents import run, invoke_rag_agent, invoke_sql_agent, invoke_graph_agent, invoke_query_analyzer_agent, invoke_planner_agent, invoke_evidence_agent, invoke_critic_agent
from .evaluation import evaluate_retrieval

app=FastAPI(title="RAGFlow Enterprise AI", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.on_event("startup")
def startup(): initialize()

@app.get("/health")
def health(): return {"status":"healthy","services":{"database":"ready","retrieval":"local-hybrid","graph":"local-adapter"}}

@app.get("/metrics")
def metrics():
    with connection() as conn:
        runs=conn.execute("SELECT count(*) c FROM agent_runs").fetchone()["c"]
        docs=conn.execute("SELECT count(*) c FROM documents").fetchone()["c"]
    return f"agent_requests_total {runs}\nragflow_documents_total {docs}\n"

@app.post("/api/auth/register")
def register(body:RegisterRequest):
    with connection() as conn: is_first = not bool(conn.execute("SELECT 1 FROM users LIMIT 1").fetchone())
    # Never let later public registrations self-assign a privileged role.
    assigned_role = "admin" if is_first else "employee"
    user={"id":str(uuid4()),"name":body.name,"email":str(body.email).lower(),"role":assigned_role}
    try:
        with connection() as conn: conn.execute("INSERT INTO users(id,name,email,password_hash,role) VALUES(?,?,?,?,?)", (*user.values(),hash_password(body.password)))
    except Exception as exc:
        if "UNIQUE" in str(exc): raise HTTPException(409,"Email already registered")
        raise
    audit(user["id"],"register","user")
    return {"access_token":token_for(user),"token_type":"bearer","user":user}

@app.post("/api/auth/login")
def login(body:LoginRequest):
    with connection() as conn: row=conn.execute("SELECT * FROM users WHERE email=?",(str(body.email).lower(),)).fetchone()
    if not row or not verify_password(body.password,row["password_hash"]): raise HTTPException(401,"Invalid email or password")
    user={k:row[k] for k in ("id","name","email","role")}; audit(user["id"],"login","session")
    return {"access_token":token_for(user),"token_type":"bearer","user":user}

def extract(filename: str, raw: bytes) -> str:
    suffix=Path(filename).suffix.lower()
    if suffix not in {".txt", ".md", ".csv", ".json", ".pdf", ".docx", ".xlsx"}: raise HTTPException(415,"Supported formats: PDF, DOCX, TXT, CSV, XLSX, Markdown")
    try:
        if suffix == ".docx":
            from docx import Document
            document = Document(BytesIO(raw))
            parts = [p.text for p in document.paragraphs if p.text.strip()]
            for table in document.tables:
                parts.extend(" | ".join(cell.text.strip() for cell in row.cells) for row in table.rows)
            return "\n".join(parts)
        if suffix == ".pdf":
            from pypdf import PdfReader
            return "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(raw)).pages)
        if suffix == ".xlsx":
            from openpyxl import load_workbook
            workbook = load_workbook(BytesIO(raw), read_only=True, data_only=True)
            rows = []
            for sheet in workbook.worksheets:
                rows.append(f"Sheet: {sheet.title}")
                rows.extend(" | ".join("" if value is None else str(value) for value in row) for row in sheet.iter_rows(values_only=True))
            return "\n".join(rows)
        return raw.decode("utf-8-sig", errors="replace")
    except Exception as exc:
        raise HTTPException(422, f"Unable to extract text from {suffix[1:].upper()} file: {exc}")

@app.post("/api/documents/upload")
async def upload(file:UploadFile=File(...), user=Depends(current_user)):
    raw=await file.read()
    if len(raw)>MAX_UPLOAD_BYTES: raise HTTPException(413,"File exceeds upload limit")
    text=extract(file.filename or "upload.txt",raw)
    if len(text.strip()) < 3: raise HTTPException(422,"No extractable text found")
    if re.search(r"ignore (all |previous )?instructions|reveal .*confidential|system prompt",text,re.I):
        audit(user["id"],"blocked_prompt_injection",file.filename or "upload"); raise HTTPException(422,"Document blocked by prompt-injection guard")
    did=str(uuid4()); pieces=chunk(text)
    # BUG-12/21 fix: store a 200-char preview in content so the documents list is useful
    content_preview = text.strip()[:200]
    with connection() as conn:
        conn.execute("INSERT INTO documents(id,user_id,filename,file_type,content,status) VALUES(?,?,?,?,?,?)",(did,user["id"],file.filename,Path(file.filename or "").suffix,content_preview,"ready"))
        conn.executemany("INSERT INTO chunks(id,document_id,text,ordinal) VALUES(?,?,?,?)",[(str(uuid4()),did,p,i) for i,p in enumerate(pieces)])
    audit(user["id"],"upload",did)
    return {"id":did,"filename":file.filename,"status":"ready","chunks":len(pieces)}

@app.get("/api/documents")
def documents(user=Depends(current_user)):
    with connection() as conn: rows=conn.execute("SELECT id,filename,file_type,status,created_at FROM documents WHERE user_id=? ORDER BY created_at DESC",(user["id"],)).fetchall()
    return [dict(x) for x in rows]

@app.delete("/api/documents/{document_id}")
def delete_document(document_id:str,user=Depends(current_user)):
    with connection() as conn:
        if not conn.execute("SELECT 1 FROM documents WHERE id=? AND user_id=?",(document_id,user["id"])).fetchone(): raise HTTPException(404,"Document not found")
        conn.execute("DELETE FROM chunks WHERE document_id=?",(document_id,)); conn.execute("DELETE FROM documents WHERE id=?",(document_id,))
    audit(user["id"],"delete_document",document_id); return {"deleted":True}

@app.post("/api/search")
def retrieve(body:ChatRequest,user=Depends(current_user)): return {"results":search(body.query,user["id"])}

@app.post("/api/documents/reindex")
def reindex(user=Depends(current_user)):
    # Chunks are persisted at upload time; this endpoint makes the reindex operation observable and auditable.
    audit(user["id"], "reindex", "documents")
    with connection() as conn: count=conn.execute("SELECT count(*) c FROM chunks c JOIN documents d ON c.document_id=d.id WHERE d.user_id=?",(user["id"],)).fetchone()["c"]
    return {"status":"completed", "indexed_chunks":count}

@app.post("/api/sql/query")
def safe_sql(body:SQLRequest,user=Depends(current_user)):
    query=validate_read_only_sql(body.query)
    try:
        with connection() as conn: rows=[dict(row) for row in conn.execute(query).fetchall()]
    except Exception as exc: raise HTTPException(422, f"SQL execution rejected: {exc}")
    audit(user["id"],"sql_query","sales")
    return {"rows":rows,"count":len(rows),"read_only":True}

@app.post("/api/chat")
def chat(body:ChatRequest,user=Depends(current_user)):
    agent_id = body.agent_id or "supervisor"
    if agent_id and agent_id != "supervisor":
        dispatch = {
            "rag":            lambda: invoke_rag_agent(body.query, user["id"]),
            "sql":            lambda: invoke_sql_agent(body.query, user["id"]),
            "graph":          lambda: invoke_graph_agent(body.query, user["id"]),
            "response":       lambda: run(body.query, user["id"]),
            "query_analyzer": lambda: invoke_query_analyzer_agent(body.query, user["id"]),
            "planner":        lambda: invoke_planner_agent(body.query, user["id"]),
            "evidence":       lambda: invoke_evidence_agent(body.query, user["id"]),
            "critic":         lambda: invoke_critic_agent(body.query, user["id"]),
        }
        fn = dispatch.get(agent_id, lambda: run(body.query, user["id"]))
        res = fn()
        if "answer" not in res:
            res = {"answer": str(res), "citations": [], "confidence": res.get("context_relevance", 0), "workflow": {"latency_ms": 1}}
        result = {
            "answer": res["answer"],
            "citations": res.get("citations", []),
            "confidence": res.get("confidence", 1.0),
            "workflow": res.get("workflow", {"intent": "single_agent", "complexity": "simple", "sources": [agent_id], "plan": [f"Execute {agent_id} agent"], "latency_ms": res.get("latency_ms", 1)})
        }
    else:
        result = run(body.query, user["id"])

    cid = body.conversation_id or str(uuid4())
    with connection() as conn:
        conn.execute("INSERT OR IGNORE INTO conversations(id,user_id,title) VALUES(?,?,?)", (cid, user["id"], body.query[:80]))
        conn.executemany("INSERT INTO messages(id,conversation_id,role,content) VALUES(?,?,?,?)", [(str(uuid4()), cid, "user", body.query), (str(uuid4()), cid, "assistant", result["answer"])])
        conn.execute("INSERT INTO agent_runs(id,user_id,query,status,latency_ms,agent_id) VALUES(?,?,?,?,?,?)", (str(uuid4()), user["id"], body.query, "completed", result.get("workflow", {}).get("latency_ms", 1), agent_id))
    audit(user["id"], f"chat:{agent_id}", cid)
    return {"conversation_id": cid, "agent_id": agent_id, **result}

@app.get("/api/chat/{conversation_id}")
def history(conversation_id:str,user=Depends(current_user)):
    with connection() as conn:
        allowed=conn.execute("SELECT 1 FROM conversations WHERE id=? AND user_id=?",(conversation_id,user["id"])).fetchone()
        if not allowed: raise HTTPException(404,"Conversation not found")
        rows=conn.execute("SELECT role,content,created_at FROM messages WHERE conversation_id=? ORDER BY created_at",(conversation_id,)).fetchall()
    return [dict(x) for x in rows]

# Enriched agent list
AGENT_DESCRIPTIONS = {
    "supervisor":      "Orchestrates all other agents to produce a grounded answer",
    "query_analyzer":  "Classifies intent, complexity, and required data sources",
    "planner":         "Builds the step-by-step retrieval plan",
    "rag":             "Retrieves relevant chunks from your uploaded documents",
    "sql":             "Queries the structured sales database",
    "graph":           "Explores organisational relationships and hierarchies",
    "evidence":        "Scores and ranks retrieved evidence by relevance",
    "critic":          "Evaluates answer quality and flags uncertainty",
    "response":        "Synthesises all evidence into a final cited answer",
}

@app.get("/api/agents")
def agents(user=Depends(current_user)):
    agent_ids = list(AGENT_DESCRIPTIONS.keys())
    with connection() as conn:
        stats = {row["agent_id"]: dict(row) for row in conn.execute(
            "SELECT agent_id, count(*) run_count, max(created_at) last_run FROM agent_runs WHERE user_id=? AND agent_id IS NOT NULL GROUP BY agent_id",
            (user["id"],)
        ).fetchall()}
    return [
        {
            "id": aid,
            "status": "ready",
            "description": AGENT_DESCRIPTIONS[aid],
            "run_count": stats.get(aid, {}).get("run_count", 0),
            "last_run": stats.get(aid, {}).get("last_run"),
        }
        for aid in agent_ids
    ]

@app.get("/api/agents/runs")
def agent_runs(user=Depends(current_user)):
    with connection() as conn: rows=conn.execute("SELECT id,query,status,latency_ms,agent_id,created_at FROM agent_runs WHERE user_id=? ORDER BY created_at DESC LIMIT 50",(user["id"],)).fetchall()
    return [dict(row) for row in rows]

@app.get("/api/agents/metrics")
def agent_metrics(user=Depends(current_user)):
    with connection() as conn: row=conn.execute("SELECT count(*) total,coalesce(avg(latency_ms),0) average_latency FROM agent_runs WHERE user_id=?",(user["id"],)).fetchone()
    return {"total_runs":row["total"],"success_rate":100 if row["total"] else 0,"average_latency_ms":round(row["average_latency"])}

# Per-agent invocation endpoint
@app.post("/api/agents/{agent_id}/invoke")
def invoke_agent(agent_id: str, body: ChatRequest, user=Depends(current_user)):
    started = perf_counter()
    dispatch = {
        "rag":            lambda: invoke_rag_agent(body.query, user["id"]),
        "sql":            lambda: invoke_sql_agent(body.query, user["id"]),
        "graph":          lambda: invoke_graph_agent(body.query, user["id"]),
        "supervisor":     lambda: run(body.query, user["id"]),
        "response":       lambda: run(body.query, user["id"]),
        "query_analyzer": lambda: invoke_query_analyzer_agent(body.query, user["id"]),
        "planner":        lambda: invoke_planner_agent(body.query, user["id"]),
        "evidence":       lambda: invoke_evidence_agent(body.query, user["id"]),
        "critic":         lambda: invoke_critic_agent(body.query, user["id"]),
    }
    if agent_id not in dispatch:
        raise HTTPException(404, f"Agent '{agent_id}' not found. Available: {', '.join(dispatch)}")
    result = dispatch[agent_id]()
    latency = round((perf_counter() - started) * 1000)
    with connection() as conn:
        conn.execute(
            "INSERT INTO agent_runs(id,user_id,query,status,latency_ms,agent_id) VALUES(?,?,?,?,?,?)",
            (str(uuid4()), user["id"], body.query, "completed", latency, agent_id)
        )
    audit(user["id"], f"invoke_agent:{agent_id}", "agents")
    if "answer" not in result:
        result = {"answer": str(result), "citations": [], "confidence": result.get("context_relevance", 0), "latency_ms": latency}
    return {"agent_id": agent_id, **result}

@app.get("/api/analytics/overview")
def analytics(user=Depends(current_user)):
    with connection() as conn:
        docs=conn.execute("SELECT count(*) c FROM documents WHERE user_id=?",(user["id"],)).fetchone()["c"]
        row=conn.execute("SELECT count(*) runs, coalesce(avg(latency_ms),0) latency FROM agent_runs WHERE user_id=?",(user["id"],)).fetchone()
    return {"documents":docs,"queries":row["runs"],"active_agents":9,"average_latency_ms":round(row["latency"]),"success_rate":100 if row["runs"] else 0}

@app.post("/api/evaluation/retrieval")
def evaluate(body:ChatRequest, user=Depends(current_user)):
    result=evaluate_retrieval(body.query,user["id"])
    audit(user["id"],"evaluate_retrieval","rag")
    return result
