from datetime import datetime, timedelta
import jwt
from jose import jwt as jose_jwt
from passlib.context import CryptContext

from app.core.config import settings

# Configuración del motor de hasheo usando bcryptss
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifica si una contraseña en texto plano coincide con su hash."""
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    """Genera el hash bcrypt de una contraseña."""
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """Crea y firma un JWT (JSON Web Token) válido."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        # Por defecto expira en los minutos definidos en el entorno
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jose_jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt

def decode_token(token: str) -> dict:
    """Decodifica un JWT y devuelve su contenido (payload)."""
    return jose_jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
