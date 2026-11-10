"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "max_running_sandboxes",
            sa.Integer(),
            server_default=sa.text("5"),
            nullable=False,
        ),
        sa.Column(
            "max_exec_timeout_ms",
            sa.Integer(),
            server_default=sa.text("60000"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "max_running_sandboxes > 0",
            name="ck_tenants_max_running_sandboxes_positive",
        ),
        sa.CheckConstraint(
            "max_exec_timeout_ms > 0",
            name="ck_tenants_max_exec_timeout_ms_positive",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "sandboxes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("vm_id", sa.Text(), nullable=True),
        sa.Column("image", sa.Text(), nullable=False),
        sa.Column("vm_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'stopped', 'failed')",
            name="ck_sandboxes_status",
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["sandboxes.id"],
            name="fk_sandboxes_parent_id_sandboxes",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_sandboxes_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("vm_id", name="uq_sandboxes_vm_id"),
    )
    op.create_index(
        "ix_sandboxes_tenant_id_status",
        "sandboxes",
        ["tenant_id", "status"],
    )
    op.create_index("ix_sandboxes_expires_at", "sandboxes", ["expires_at"])
    op.create_index("ix_sandboxes_parent_id", "sandboxes", ["parent_id"])

    op.create_table(
        "api_keys",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("key_prefix", sa.String(length=8), nullable=False),
        sa.Column("key_hash", sa.LargeBinary(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_api_keys_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key_hash", name="uq_api_keys_key_hash"),
    )
    op.create_index("ix_api_keys_tenant_id", "api_keys", ["tenant_id"])
    op.create_index(
        "ix_api_keys_key_prefix_active",
        "api_keys",
        ["key_prefix"],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_api_keys_key_prefix_active", table_name="api_keys")
    op.drop_index("ix_api_keys_tenant_id", table_name="api_keys")
    op.drop_table("api_keys")

    op.drop_index("ix_sandboxes_parent_id", table_name="sandboxes")
    op.drop_index("ix_sandboxes_expires_at", table_name="sandboxes")
    op.drop_index("ix_sandboxes_tenant_id_status", table_name="sandboxes")
    op.drop_table("sandboxes")

    op.drop_table("tenants")
