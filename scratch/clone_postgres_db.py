import os
import subprocess
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg import sql

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _normalize_sync_url(url: str) -> str:
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql://", 1)
    return url


def _load_models_metadata():
    from app.core.database import Base

    import app.packages.identity.domain.models  # noqa: F401
    import app.packages.workshops.domain.models  # noqa: F401
    import app.packages.emergencies.domain.models  # noqa: F401
    import app.packages.assignment.domain.models  # noqa: F401
    import app.packages.finance.domain.models  # noqa: F401
    import app.packages.scheduling.domain.models  # noqa: F401
    import app.packages.quotations.domain.models  # noqa: F401

    return Base.metadata


def _copy_table(source_conn, target_conn, table):
    columns = [column.name for column in table.columns]
    identifiers = [sql.Identifier(column) for column in columns]
    table_ident = sql.Identifier(table.name)

    copy_out = sql.SQL("COPY {} ({}) TO STDOUT WITH (FORMAT BINARY)").format(
        table_ident,
        sql.SQL(", ").join(identifiers),
    )
    copy_in = sql.SQL("COPY {} ({}) FROM STDIN WITH (FORMAT BINARY)").format(
        table_ident,
        sql.SQL(", ").join(identifiers),
    )

    print(f"Copiando tabla: {table.name}")
    with source_conn.cursor().copy(copy_out) as exporter:
        with target_conn.cursor().copy(copy_in) as importer:
            for chunk in exporter:
                importer.write(chunk)


def _sync_sequences(source_conn, target_conn):
    query = """
        SELECT schemaname, sequencename, last_value
        FROM pg_sequences
        WHERE schemaname = 'public'
    """
    with source_conn.cursor() as cursor:
        cursor.execute(query)
        sequences = cursor.fetchall()

    for schema_name, sequence_name, last_value in sequences:
        if last_value is None:
            continue
        qualified = f"{schema_name}.{sequence_name}"
        with target_conn.cursor() as cursor:
            cursor.execute("SELECT setval(%s, %s, true)", (qualified, last_value))


def _truncate_target(target_conn, table_names):
    if not table_names:
        return
    query = sql.SQL("TRUNCATE {} RESTART IDENTITY CASCADE").format(
        sql.SQL(", ").join(sql.Identifier(name) for name in table_names)
    )
    with target_conn.cursor() as cursor:
        cursor.execute(query)


def _run_alembic_on_target(target_async_url: str):
    env = os.environ.copy()
    env["DATABASE_URL"] = target_async_url
    env.setdefault("SECRET_KEY", "temp-migration-secret")

    print("Aplicando migraciones en la base destino...")
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=PROJECT_ROOT,
        env=env,
        check=True,
    )


def main():
    load_dotenv(PROJECT_ROOT / ".env")

    source_async_url = os.getenv("SOURCE_DATABASE_URL") or os.getenv("DATABASE_URL")
    target_async_url = os.getenv("TARGET_DATABASE_URL")

    if not source_async_url:
        raise SystemExit("Falta SOURCE_DATABASE_URL o DATABASE_URL.")
    if not target_async_url:
        raise SystemExit("Falta TARGET_DATABASE_URL.")

    source_sync_url = _normalize_sync_url(source_async_url)
    target_sync_url = _normalize_sync_url(target_async_url)

    metadata = _load_models_metadata()
    ordered_tables = [
        table for table in metadata.sorted_tables if table.name != "alembic_version"
    ]
    ordered_names = [table.name for table in ordered_tables]

    _run_alembic_on_target(target_async_url)

    print("Conectando a origen y destino...")
    with psycopg.connect(source_sync_url) as source_conn, psycopg.connect(target_sync_url) as target_conn:
        source_conn.autocommit = False
        target_conn.autocommit = False

        print("Limpiando tablas destino...")
        _truncate_target(target_conn, list(reversed(ordered_names)))

        for table in ordered_tables:
            _copy_table(source_conn, target_conn, table)

        print("Sincronizando secuencias...")
        _sync_sequences(source_conn, target_conn)

        target_conn.commit()
        print("Clonación completada.")


if __name__ == "__main__":
    main()
