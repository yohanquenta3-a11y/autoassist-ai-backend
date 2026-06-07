"""add offline incident sync fields

Revision ID: d42d4c1f8b0a
Revises: b1a9c6d4e2f7
Create Date: 2026-06-06 18:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d42d4c1f8b0a"
down_revision: Union[str, Sequence[str], None] = "b1a9c6d4e2f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("incidente", sa.Column("identificador_local", sa.String(length=120), nullable=True))
    op.add_column(
        "incidente",
        sa.Column("origen_registro", sa.String(length=50), nullable=False, server_default="ONLINE"),
    )
    op.add_column("incidente", sa.Column("fecha_sincronizacion", sa.DateTime(), nullable=True))
    op.create_index(
        "uq_incidente_usuario_identificador_local",
        "incidente",
        ["id_usuario_cliente", "identificador_local"],
        unique=True,
        postgresql_where=sa.text("identificador_local IS NOT NULL"),
    )
    op.alter_column("incidente", "origen_registro", server_default=None)


def downgrade() -> None:
    op.drop_index("uq_incidente_usuario_identificador_local", table_name="incidente")
    op.drop_column("incidente", "fecha_sincronizacion")
    op.drop_column("incidente", "origen_registro")
    op.drop_column("incidente", "identificador_local")
