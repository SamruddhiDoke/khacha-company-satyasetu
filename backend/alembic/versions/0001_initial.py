"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-10
"""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("last_seen_at", TS, nullable=False),
        sa.Column("preferences", sa.JSON(), nullable=False),
    )
    op.create_table(
        "conversations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
    )
    op.create_index("ix_conversations_session_id", "conversations", ["session_id"])
    op.create_table(
        "attachments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_path", sa.String(500), nullable=False),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("extraction", sa.JSON(), nullable=False),
        sa.Column("created_at", TS, nullable=False),
    )
    op.create_index("ix_attachments_session_id", "attachments", ["session_id"])
    op.create_table(
        "messages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("conversation_id", sa.Uuid(), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(10), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("attachment_id", sa.Uuid(), sa.ForeignKey("attachments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.UniqueConstraint("conversation_id", "seq"),
    )
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])
    op.create_table(
        "verification_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("message_id", sa.Uuid(), sa.ForeignKey("messages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("language", sa.String(5), nullable=False),
        sa.Column("input_text", sa.Text(), nullable=False),
        sa.Column("input_sha256", sa.String(64), nullable=False),
        sa.Column("overall_verdict", sa.String(30), nullable=True),
        sa.Column("evidence_strength", sa.String(12), nullable=True),
        sa.Column("explanation", sa.JSON(), nullable=True),
        sa.Column("harm", sa.JSON(), nullable=True),
        sa.Column("content_meta", sa.JSON(), nullable=True),
        sa.Column("models_used", sa.JSON(), nullable=False),
        sa.Column("usage", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(40), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("started_at", TS, nullable=True),
        sa.Column("finished_at", TS, nullable=True),
    )
    op.create_index("ix_verification_jobs_message_id", "verification_jobs", ["message_id"])
    op.create_index("ix_verification_jobs_session_id", "verification_jobs", ["session_id"])
    op.create_index("uq_active_job_per_message", "verification_jobs", ["message_id"], unique=True,
                    postgresql_where=sa.text("status IN ('queued','running')"))
    op.create_table(
        "verification_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey("verification_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("stage", sa.String(40), nullable=True),
        sa.Column("status", sa.String(12), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.UniqueConstraint("job_id", "seq"),
    )
    op.create_index("ix_verification_events_job_id", "verification_events", ["job_id"])
    op.create_table(
        "claims",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey("verification_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("idx", sa.Integer(), nullable=False),
        sa.Column("original_text", sa.Text(), nullable=False),
        sa.Column("span_found", sa.Boolean(), nullable=False),
        sa.Column("normalized", sa.Text(), nullable=False),
        sa.Column("claim_type", sa.String(20), nullable=False),
        sa.Column("checkable", sa.Boolean(), nullable=False),
        sa.Column("reason_not_checkable", sa.Text(), nullable=True),
        sa.Column("entities", sa.JSON(), nullable=False),
        sa.Column("dates", sa.JSON(), nullable=False),
        sa.Column("numbers", sa.JSON(), nullable=False),
        sa.Column("attribution", sa.Text(), nullable=True),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column("topic", sa.String(40), nullable=True),
        sa.Column("queries", sa.JSON(), nullable=False),
        sa.Column("verdict", sa.String(30), nullable=True),
        sa.Column("evidence_strength", sa.String(12), nullable=True),
        sa.Column("verdict_reason", sa.Text(), nullable=True),
        sa.Column("missing_context", sa.Text(), nullable=True),
        sa.Column("conflict_note", sa.Text(), nullable=True),
        sa.Column("what_would_change", sa.Text(), nullable=True),
        sa.Column("weights", sa.JSON(), nullable=False),
    )
    op.create_index("ix_claims_job_id", "claims", ["job_id"])
    op.create_table(
        "sources",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey("verification_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("final_url", sa.Text(), nullable=True),
        sa.Column("domain", sa.String(255), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("publisher", sa.String(255), nullable=True),
        sa.Column("published_date", sa.String(40), nullable=True),
        sa.Column("tier", sa.String(20), nullable=False),
        sa.Column("found_via", sa.String(30), nullable=False),
        sa.Column("retrieval_method", sa.String(30), nullable=True),
        sa.Column("retrieved_at", TS, nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("fetch_ok", sa.Boolean(), nullable=False),
        sa.Column("fetch_error", sa.Text(), nullable=True),
        sa.Column("content_sha256", sa.String(64), nullable=True),
        sa.Column("content_text", sa.Text(), nullable=True),
        sa.Column("search_score", sa.Float(), nullable=True),
        sa.Column("factcheck_rating", sa.String(255), nullable=True),
    )
    op.create_index("ix_sources_job_id", "sources", ["job_id"])
    op.create_table(
        "evidence",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("claim_id", sa.Uuid(), sa.ForeignKey("claims.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", sa.Uuid(), sa.ForeignKey("sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("passage", sa.Text(), nullable=False),
        sa.Column("quote", sa.Text(), nullable=True),
        sa.Column("stance", sa.String(24), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("quote_valid", sa.Boolean(), nullable=False),
        sa.Column("rejected_reason", sa.Text(), nullable=True),
        sa.Column("temporal_issue", sa.Boolean(), nullable=False),
        sa.Column("missing_context", sa.Text(), nullable=True),
        sa.Column("counted", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_evidence_claim_id", "evidence", ["claim_id"])
    op.create_index("ix_evidence_source_id", "evidence", ["source_id"])
    op.create_table(
        "corrections",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey("verification_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("relationship_to", sa.String(20), nullable=False),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("language", sa.String(5), nullable=False),
        sa.Column("tone", sa.String(20), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("generator", sa.String(30), nullable=False),
        sa.Column("validation", sa.JSON(), nullable=False),
        sa.Column("created_at", TS, nullable=False),
    )
    op.create_index("ix_corrections_job_id", "corrections", ["job_id"])
    op.create_table(
        "document_findings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey("verification_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category", sa.String(30), nullable=False),
        sa.Column("check", sa.String(60), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("location", sa.JSON(), nullable=True),
    )
    op.create_index("ix_document_findings_job_id", "document_findings", ["job_id"])
    op.create_table(
        "provider_usage",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("requests", sa.Integer(), nullable=False),
        sa.Column("units", sa.BigInteger(), nullable=False),
        sa.Column("errors", sa.Integer(), nullable=False),
        sa.UniqueConstraint("provider", "day"),
    )


def downgrade() -> None:
    for t in ("provider_usage", "document_findings", "corrections", "evidence", "sources", "claims",
              "verification_events", "verification_jobs", "messages", "attachments", "conversations", "sessions"):
        op.drop_table(t)
