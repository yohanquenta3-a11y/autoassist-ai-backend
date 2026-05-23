from pydantic import BaseModel, EmailStr, Field
from typing import Optional
import uuid


# --- Requests (Entrada) ---

class UserCreate(BaseModel):
    nombre: str = Field(..., max_length=150)
    telefono: Optional[str] = Field(None, max_length=20)
    correo: EmailStr
    contrasena: str = Field(..., min_length=6)


class UserAdminCreate(UserCreate):
    rol_nombre: str
    id_taller: Optional[uuid.UUID] = None


class UserLogin(BaseModel):
    correo: EmailStr
    contrasena: str


# --- Responses (Salida) ---

class UserResponse(BaseModel):
    id_usuario: uuid.UUID
    nombre: str
    telefono: Optional[str]
    correo: EmailStr
    rol_nombre: str
    estado: bool

    model_config = {"from_attributes": True}


class TokenSchema(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse