import sqlite3
from contextlib import contextmanager
from pathlib import Path
from .config import DATABASE_URL

def db_path() -> str:
    value = DATABASE_URL.removeprefix("sqlite:///")
    Path(value).parent.mkdir(parents=True, exist_ok=True)
    return value

@contextmanager
def connection():
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def initialize() -> None:
    with connection() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS documents (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, filename TEXT NOT NULL, file_type TEXT NOT NULL, content TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS chunks (id TEXT PRIMARY KEY, document_id TEXT NOT NULL, text TEXT NOT NULL, ordinal INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS conversations (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, title TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS messages (id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS agent_runs (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, query TEXT NOT NULL, status TEXT NOT NULL, latency_ms INTEGER, agent_id TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS audit_logs (id TEXT PRIMARY KEY, user_id TEXT, action TEXT NOT NULL, resource TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS sales (region TEXT NOT NULL, quarter TEXT NOT NULL, revenue REAL NOT NULL, manager TEXT NOT NULL, PRIMARY KEY (region, quarter));
        CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id);
        CREATE INDEX IF NOT EXISTS idx_documents_user ON documents(user_id);
        CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id);
        CREATE INDEX IF NOT EXISTS idx_agent_runs_user ON agent_runs(user_id);
        """)
        # Ensure agent_id column exists on existing databases (safe migration)
        existing_cols = [row[1] for row in conn.execute("PRAGMA table_info(agent_runs)").fetchall()]
        if "agent_id" not in existing_cols:
            conn.execute("ALTER TABLE agent_runs ADD COLUMN agent_id TEXT")
        if not conn.execute("SELECT 1 FROM sales LIMIT 1").fetchone():
            conn.executemany("INSERT INTO sales VALUES (?, ?, ?, ?)", [("North", "Q3", 82000, "Asha Patel"), ("South", "Q3", 94000, "Rahul Shah"), ("West", "Q3", 76000, "Meera Singh")])

