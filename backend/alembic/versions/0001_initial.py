"""initial schema (users, workflows, steps, documents, pgvector chunks, approvals, audit logs)"""
import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

from app.config import get_settings

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table("users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("created_at", TS, nullable=False), sa.Column("updated_at", TS, nullable=False))
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table("workflows",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(255), nullable=False), sa.Column("description", sa.Text, nullable=False),
        sa.Column("status", sa.String(32), nullable=False), sa.Column("require_approval", sa.Boolean, nullable=False),
        sa.Column("plan", sa.JSON), sa.Column("result", sa.JSON), sa.Column("error", sa.Text),
        sa.Column("created_at", TS, nullable=False), sa.Column("started_at", TS), sa.Column("completed_at", TS))
    op.create_index("ix_workflows_user_id", "workflows", ["user_id"])
    op.create_index("ix_workflows_status", "workflows", ["status"])

    op.create_table("workflow_steps",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("workflow_id", sa.Integer, sa.ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False),
        sa.Column("step_number", sa.Integer, nullable=False), sa.Column("name", sa.String(255), nullable=False),
        sa.Column("step_type", sa.String(32), nullable=False), sa.Column("status", sa.String(32), nullable=False),
        sa.Column("tool_name", sa.String(64)), sa.Column("input_data", sa.JSON), sa.Column("output_data", sa.JSON),
        sa.Column("error", sa.Text), sa.Column("started_at", TS), sa.Column("completed_at", TS),
        sa.Column("duration", sa.Float))
    op.create_index("ix_workflow_steps_workflow_id", "workflow_steps", ["workflow_id"])

    op.create_table("documents",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False), sa.Column("file_type", sa.String(16), nullable=False),
        sa.Column("file_size", sa.Integer, nullable=False), sa.Column("status", sa.String(16), nullable=False),
        sa.Column("storage_path", sa.String(512), nullable=False), sa.Column("error", sa.Text),
        sa.Column("metadata", sa.JSON), sa.Column("created_at", TS, nullable=False))
    op.create_index("ix_documents_user_id", "documents", ["user_id"])

    op.create_table("document_chunks",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("document_id", sa.Integer, sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chunk_index", sa.Integer, nullable=False), sa.Column("content", sa.Text, nullable=False),
        sa.Column("embedding", Vector(get_settings().embedding_dim)), sa.Column("metadata", sa.JSON))
    op.create_index("ix_document_chunks_document_id", "document_chunks", ["document_id"])
    op.execute("CREATE INDEX ix_document_chunks_embedding ON document_chunks USING hnsw (embedding vector_cosine_ops)")

    op.create_table("approvals",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("workflow_id", sa.Integer, sa.ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False),
        sa.Column("step_id", sa.Integer, sa.ForeignKey("workflow_steps.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action", sa.String(255), nullable=False), sa.Column("reason", sa.Text, nullable=False),
        sa.Column("status", sa.String(16), nullable=False), sa.Column("note", sa.Text),
        sa.Column("created_at", TS, nullable=False), sa.Column("resolved_at", TS))
    op.create_index("ix_approvals_workflow_id", "approvals", ["workflow_id"])

    op.create_table("audit_logs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("workflow_id", sa.Integer, sa.ForeignKey("workflows.id", ondelete="CASCADE")),
        sa.Column("event_type", sa.String(64), nullable=False), sa.Column("message", sa.Text, nullable=False),
        sa.Column("metadata", sa.JSON), sa.Column("created_at", TS, nullable=False))
    op.create_index("ix_audit_logs_user_id", "audit_logs", ["user_id"])
    op.create_index("ix_audit_logs_workflow_id", "audit_logs", ["workflow_id"])


def downgrade() -> None:
    for t in ("audit_logs", "approvals", "document_chunks", "documents", "workflow_steps", "workflows", "users"):
        op.drop_table(t)
