import os
from pathlib import Path

def _load_env():
    for base in [Path.cwd(), Path(__file__).resolve().parent.parent.parent]:
        env_path = base / ".env"
        if env_path.is_file():
            try:
                for line in env_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k, v = k.strip(), v.strip().strip('"').strip("'")
                        if k not in os.environ:
                            os.environ[k] = v
                break
            except Exception:
                pass

_load_env()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./ragflow.db")
JWT_SECRET = os.getenv("JWT_SECRET", "development-secret-change-me")
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", "10485760"))
REDIS_URL = os.getenv("REDIS_URL", "")
QDRANT_URL = os.getenv("QDRANT_URL", "")
NEO4J_URI = os.getenv("NEO4J_URI", "")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

