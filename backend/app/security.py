import re
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext
from .config import JWT_SECRET
from .database import connection

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer = HTTPBearer(auto_error=False)

def hash_password(value: str) -> str: return pwd.hash(value)
def verify_password(value: str, hashed: str) -> bool: return pwd.verify(value, hashed)
def token_for(user: dict) -> str:
    return jwt.encode({"sub": user["id"], "role": user["role"], "exp": datetime.now(timezone.utc) + timedelta(hours=8)}, JWT_SECRET, algorithm="HS256")

def current_user(credentials: HTTPAuthorizationCredentials = Depends(bearer)) -> dict:
    if not credentials: raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required")
    try: payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError: raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    with connection() as conn:
        row = conn.execute("SELECT id,name,email,role FROM users WHERE id=?", (payload["sub"],)).fetchone()
    if not row: raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    return dict(row)

def require_roles(*roles):
    def guard(user=Depends(current_user)):
        if user["role"] not in roles: raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
        return user
    return guard

def audit(user_id: str | None, action: str, resource: str):
    with connection() as conn: conn.execute("INSERT INTO audit_logs(id,user_id,action,resource) VALUES(?,?,?,?)", (str(uuid4()), user_id, action, resource))

def validate_read_only_sql(query: str) -> str:
    stripped = " ".join(query.strip().split()).rstrip(";")
    if not stripped.lower().startswith("select") or ";" in stripped:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Only one read-only SELECT statement is permitted")
    blocked = ("insert", "update", "delete", "drop", "alter", "truncate", "attach", "pragma", "create")
    lower_query = stripped.lower()
    if any(re.search(r"\b" + re.escape(word) + r"\b", lower_query) for word in blocked):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unsafe SQL keyword blocked")
    return stripped

