import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Alembic Config object
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# --- Importar Base y Settings ---
from app.core.database import Base
from app.core.config import settings

# --- Importar TODOS los modelos para que Alembic los detecte en el autogenerate ---
# Identity
import app.packages.identity.domain.models          # Rol, Usuario, Vehiculo, Bitacora, Notificacion
# Workshops
import app.packages.workshops.domain.models          # Taller, Tecnico, AdministradorTaller, etc.
# Emergencies
import app.packages.emergencies.domain.models        # Incidente, EvidenciaIncidente, HistorialIncidente
# Assignment
import app.packages.assignment.domain.models         # AsignacionIncidente
# Finance
import app.packages.finance.domain.models            # Pago
# Scheduling
import app.packages.scheduling.domain.models         # Cita
# Quotations
import app.packages.quotations.domain.models         # SolicitudCotizacion, Cotizacion
# Transfers
import app.packages.transfers.domain.models          # SolicitudTraslado, HistorialTraslado

target_metadata = Base.metadata

# Inyectar URL de la BD desde las variables de entorno (no desde alembic.ini)
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)


def include_object(object, name, type_, reflected, compare_to):
    """Excluye tablas del sistema de PostGIS para que Alembic no las gestione."""
    if type_ == "table" and name in ("spatial_ref_sys", "geography_columns", "geometry_columns"):
        return False
    return True


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
