"""add vehicle transfers

Revision ID: e7c4b2a9d011
Revises: d42d4c1f8b0a
Create Date: 2026-07-07 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e7c4b2a9d011"
down_revision: Union[str, None] = "d42d4c1f8b0a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "solicitud_traslado",
        sa.Column("id_traslado", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tipo_traslado", sa.String(length=50), nullable=False),
        sa.Column("estado", sa.String(length=50), nullable=False),
        sa.Column("id_cliente", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("id_vehiculo", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("id_taller", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("id_sucursal", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("id_tecnico", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("origen_direccion", sa.Text(), nullable=False),
        sa.Column("origen_latitud", sa.Numeric(10, 7), nullable=True),
        sa.Column("origen_longitud", sa.Numeric(10, 7), nullable=True),
        sa.Column("destino_direccion", sa.Text(), nullable=False),
        sa.Column("destino_latitud", sa.Numeric(10, 7), nullable=True),
        sa.Column("destino_longitud", sa.Numeric(10, 7), nullable=True),
        sa.Column("fecha_programada", sa.DateTime(), nullable=True),
        sa.Column("motivo", sa.Text(), nullable=False),
        sa.Column("observaciones", sa.Text(), nullable=True),
        sa.Column("telefono_contacto", sa.String(length=20), nullable=True),
        sa.Column("creado_por", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rol_creador", sa.String(length=50), nullable=False),
        sa.Column("fecha_creacion", sa.DateTime(), nullable=False),
        sa.Column("fecha_modificacion", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["creado_por"], ["usuarios.id_usuario"]),
        sa.ForeignKeyConstraint(["id_cliente"], ["usuarios.id_usuario"]),
        sa.ForeignKeyConstraint(["id_tecnico"], ["tecnico.id_tecnico"]),
        sa.ForeignKeyConstraint(["id_taller"], ["taller.id_taller"]),
        sa.ForeignKeyConstraint(["id_vehiculo"], ["vehiculo.id_vehiculo"]),
        sa.ForeignKeyConstraint(
            ["id_sucursal", "id_taller"],
            ["sucursal_taller.id_sucursal", "sucursal_taller.id_taller"],
            name="fk_solicitud_traslado_sucursal",
        ),
        sa.PrimaryKeyConstraint("id_traslado"),
    )
    op.create_index("ix_solicitud_traslado_cliente", "solicitud_traslado", ["id_cliente"])
    op.create_index("ix_solicitud_traslado_taller", "solicitud_traslado", ["id_taller"])
    op.create_index("ix_solicitud_traslado_sucursal", "solicitud_traslado", ["id_sucursal"])
    op.create_index("ix_solicitud_traslado_estado", "solicitud_traslado", ["estado"])
    op.create_index("ix_solicitud_traslado_tipo", "solicitud_traslado", ["tipo_traslado"])
    op.create_index("ix_solicitud_traslado_fecha_programada", "solicitud_traslado", ["fecha_programada"])

    op.create_table(
        "historial_traslado",
        sa.Column("id_historial", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("id_traslado", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("estado_anterior", sa.String(length=50), nullable=True),
        sa.Column("estado_nuevo", sa.String(length=50), nullable=False),
        sa.Column("historial_actor", sa.String(length=150), nullable=True),
        sa.Column("id_usuario_actor", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("comentario", sa.Text(), nullable=True),
        sa.Column("fecha", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["id_traslado"], ["solicitud_traslado.id_traslado"]),
        sa.ForeignKeyConstraint(["id_usuario_actor"], ["usuarios.id_usuario"]),
        sa.PrimaryKeyConstraint("id_historial"),
    )
    op.create_index("ix_historial_traslado_traslado", "historial_traslado", ["id_traslado"])


def downgrade() -> None:
    op.drop_index("ix_historial_traslado_traslado", table_name="historial_traslado")
    op.drop_table("historial_traslado")
    op.drop_index("ix_solicitud_traslado_fecha_programada", table_name="solicitud_traslado")
    op.drop_index("ix_solicitud_traslado_tipo", table_name="solicitud_traslado")
    op.drop_index("ix_solicitud_traslado_estado", table_name="solicitud_traslado")
    op.drop_index("ix_solicitud_traslado_sucursal", table_name="solicitud_traslado")
    op.drop_index("ix_solicitud_traslado_taller", table_name="solicitud_traslado")
    op.drop_index("ix_solicitud_traslado_cliente", table_name="solicitud_traslado")
    op.drop_table("solicitud_traslado")
