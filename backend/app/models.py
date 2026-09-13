from pydantic import BaseModel, EmailStr, Field
from typing import Literal

class RegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: Literal["admin", "manager", "employee", "viewer"] = "employee"
class LoginRequest(BaseModel): email: EmailStr; password: str
class ChatRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = None
    agent_id: str | None = None
class SQLRequest(BaseModel): query: str
