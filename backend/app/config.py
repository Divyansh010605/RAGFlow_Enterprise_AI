from os import getenv

DATABASE_URL = getenv("DATABASE_URL", "sqlite:///./ragflow.db")
JWT_SECRET = getenv("JWT_SECRET", "development-secret-change-me")
CORS_ORIGINS = getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
MAX_UPLOAD_BYTES = int(getenv("MAX_UPLOAD_BYTES", "10485760"))
REDIS_URL = getenv("REDIS_URL", "")
QDRANT_URL = getenv("QDRANT_URL", "")
NEO4J_URI = getenv("NEO4J_URI", "")
NEO4J_PASSWORD = getenv("NEO4J_PASSWORD", "")
GEMINI_API_KEY = getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = getenv("GEMINI_MODEL", "gemini-2.0-flash")
