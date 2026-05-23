from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base

from app.core.config import settings

# Motor asíncrono de SQLAlchemy para PostgreSQL (asyncpg)
# echo=True muestra las queries SQL en consola (ponlo en False en producción)
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=True,
    future=True,
    pool_recycle=3600,
    pool_pre_ping=True,
)

# Fábrica de sesiones asíncronas
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# Clase base de la que heredarán todos los modelos ORM
Base = declarative_base()


# Dependencia de FastAPI para inyectar sesión de BD en los routers
async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
