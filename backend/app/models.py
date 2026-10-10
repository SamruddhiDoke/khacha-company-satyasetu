"""Relational data model. Every child row cascades from its owning session so a
session, conversation or verification can be deleted completely."""
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> uuid.UUID:
    return uuid.uuid4()


TS = DateTime(timezone=True)


class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    preferences: Mapped[dict] = mapped_column(JSON, default=dict)


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(120), default="New conversation")
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TS, default=utcnow)

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", passive_deletes=True, order_by="Message.seq"
    )


class Attachment(Base):
    __tablename__ = "attachments"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(20))  # image | pdf | audio
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_path: Mapped[str] = mapped_column(String(500))
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    extraction: Mapped[dict] = mapped_column(JSON, default=dict)  # method, confidence, warnings, pages
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(10), default="user")  # user | system
    kind: Mapped[str] = mapped_column(String(10), default="text")  # text | url | image | pdf | audio
    text: Mapped[str] = mapped_column(Text, default="")
    attachment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("attachments.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
    attachment: Mapped[Attachment | None] = relationship(lazy="joined")
    __table_args__ = (UniqueConstraint("conversation_id", "seq"),)


ACTIVE_JOB_STATUSES = ("queued", "running")


class VerificationJob(Base):
    __tablename__ = "verification_jobs"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    message_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), index=True)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(12), default="queued")  # queued|running|completed|failed
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    language: Mapped[str] = mapped_column(String(5), default="en")
    input_text: Mapped[str] = mapped_column(Text)
    input_sha256: Mapped[str] = mapped_column(String(64))
    overall_verdict: Mapped[str | None] = mapped_column(String(30), nullable=True)
    evidence_strength: Mapped[str | None] = mapped_column(String(12), nullable=True)
    explanation: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    harm: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    content_meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # detected language, extraction notes
    models_used: Mapped[list] = mapped_column(JSON, default=list)
    usage: Mapped[dict] = mapped_column(JSON, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)

    claims: Mapped[list["Claim"]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True, order_by="Claim.idx"
    )
    sources: Mapped[list["Source"]] = relationship(cascade="all, delete-orphan", passive_deletes=True)
    findings: Mapped[list["DocumentFinding"]] = relationship(cascade="all, delete-orphan", passive_deletes=True)

    __table_args__ = (
        # At most one active job per message: prevents accidental duplicate checks.
        Index(
            "uq_active_job_per_message",
            "message_id",
            unique=True,
            postgresql_where=text("status IN ('queued','running')"),
        ),
    )


class VerificationEvent(Base):
    __tablename__ = "verification_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("verification_jobs.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(10))  # stage | done | error
    stage: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str | None] = mapped_column(String(12), nullable=True)  # started|completed|skipped|failed
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    __table_args__ = (UniqueConstraint("job_id", "seq"),)


class Claim(Base):
    __tablename__ = "claims"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("verification_jobs.id", ondelete="CASCADE"), index=True)
    idx: Mapped[int] = mapped_column(Integer)
    original_text: Mapped[str] = mapped_column(Text)
    span_found: Mapped[bool] = mapped_column(Boolean, default=False)
    normalized: Mapped[str] = mapped_column(Text)
    claim_type: Mapped[str] = mapped_column(String(20))
    checkable: Mapped[bool] = mapped_column(Boolean)
    reason_not_checkable: Mapped[str | None] = mapped_column(Text, nullable=True)
    entities: Mapped[list] = mapped_column(JSON, default=list)
    dates: Mapped[list] = mapped_column(JSON, default=list)
    numbers: Mapped[list] = mapped_column(JSON, default=list)
    attribution: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(Text, nullable=True)
    topic: Mapped[str | None] = mapped_column(String(40), nullable=True)
    queries: Mapped[list] = mapped_column(JSON, default=list)
    verdict: Mapped[str | None] = mapped_column(String(30), nullable=True)
    evidence_strength: Mapped[str | None] = mapped_column(String(12), nullable=True)
    verdict_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    missing_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    conflict_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    what_would_change: Mapped[str | None] = mapped_column(Text, nullable=True)
    weights: Mapped[dict] = mapped_column(JSON, default=dict)

    evidence: Mapped[list["Evidence"]] = relationship(cascade="all, delete-orphan", passive_deletes=True)


class Source(Base):
    __tablename__ = "sources"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("verification_jobs.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(Text)
    final_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    domain: Mapped[str] = mapped_column(String(255))
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    publisher: Mapped[str | None] = mapped_column(String(255), nullable=True)
    published_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    tier: Mapped[str] = mapped_column(String(20))  # official|fact_check|news|reference|other
    found_via: Mapped[str] = mapped_column(String(30))  # tavily | factcheck_api | user_url
    retrieval_method: Mapped[str | None] = mapped_column(String(30), nullable=True)  # direct | provider_extract
    retrieved_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fetch_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    fetch_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content_text: Mapped[str | None] = mapped_column(Text, nullable=True)  # bounded, kept for quote audit
    search_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    factcheck_rating: Mapped[str | None] = mapped_column(String(255), nullable=True)


class Evidence(Base):
    __tablename__ = "evidence"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    claim_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"), index=True)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), index=True)
    passage: Mapped[str] = mapped_column(Text)
    quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    stance: Mapped[str] = mapped_column(String(24))  # supports|refutes|partially_supports|not_relevant
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    quote_valid: Mapped[bool] = mapped_column(Boolean, default=False)
    rejected_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    temporal_issue: Mapped[bool] = mapped_column(Boolean, default=False)
    missing_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    counted: Mapped[bool] = mapped_column(Boolean, default=False)

    source: Mapped[Source] = relationship(lazy="joined")


class Correction(Base):
    __tablename__ = "corrections"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("verification_jobs.id", ondelete="CASCADE"), index=True)
    relationship_to: Mapped[str] = mapped_column(String(20))
    channel: Mapped[str] = mapped_column(String(20))
    language: Mapped[str] = mapped_column(String(5))
    tone: Mapped[str] = mapped_column(String(20))
    text: Mapped[str] = mapped_column(Text)
    generator: Mapped[str] = mapped_column(String(30))  # model:<id> | template
    validation: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class DocumentFinding(Base):
    __tablename__ = "document_findings"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("verification_jobs.id", ondelete="CASCADE"), index=True)
    category: Mapped[str] = mapped_column(String(30))  # confirmed_inconsistency|warning|could_not_check|passed
    check: Mapped[str] = mapped_column(String(60))
    title: Mapped[str] = mapped_column(Text)
    detail: Mapped[str] = mapped_column(Text)
    location: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {page, snippet}


class ProviderUsage(Base):
    __tablename__ = "provider_usage"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(30))
    day: Mapped[date] = mapped_column(Date)
    requests: Mapped[int] = mapped_column(Integer, default=0)
    units: Mapped[int] = mapped_column(BigInteger, default=0)  # tokens for LLM, credits for search
    errors: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (UniqueConstraint("provider", "day"),)
