"""API contract. The frontend's TypeScript types are generated from the OpenAPI
document produced from these models (see frontend `npm run gen:api`)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Language = Literal["en", "hi", "mr"]
JobStatus = Literal["queued", "running", "completed", "failed"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ConversationCreate(BaseModel):
    title: str | None = Field(None, max_length=120)


class ConversationUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class ConversationOut(ORM):
    id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime
    last_message_preview: str | None = None
    last_verdict: str | None = None
    last_status: str | None = None
    message_count: int = 0


class MessageCreate(BaseModel):
    text: str = Field(min_length=1, max_length=6000)


class AttachmentOut(ORM):
    id: uuid.UUID
    filename: str
    mime_type: str
    kind: str
    size_bytes: int
    extraction_method: str | None = None
    extraction_confidence: float | None = None
    extraction_warnings: list[str] = []


class JobSummary(ORM):
    id: uuid.UUID
    message_id: uuid.UUID
    status: JobStatus
    attempt: int
    language: str
    overall_verdict: str | None
    evidence_strength: str | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class MessageOut(ORM):
    id: uuid.UUID
    conversation_id: uuid.UUID
    seq: int
    role: str
    kind: str
    text: str
    created_at: datetime
    attachment: AttachmentOut | None = None
    latest_job: JobSummary | None = None


class EventOut(BaseModel):
    id: int
    seq: int
    job_id: str
    kind: str
    stage: str | None
    status: str | None
    detail: str | None
    at: str


class SourceOut(ORM):
    id: uuid.UUID
    label: str | None = None
    url: str
    final_url: str | None
    domain: str
    title: str | None
    publisher: str | None
    published_date: str | None
    tier: str
    found_via: str
    retrieval_method: str | None
    retrieved_at: datetime | None
    http_status: int | None
    fetch_ok: bool
    fetch_error: str | None
    factcheck_rating: str | None


class EvidenceOut(ORM):
    id: uuid.UUID
    source_id: uuid.UUID
    quote: str | None
    passage: str
    stance: str
    rationale: str | None
    quote_valid: bool
    rejected_reason: str | None
    temporal_issue: bool
    missing_context: str | None
    counted: bool


class ClaimOut(ORM):
    id: uuid.UUID
    idx: int
    original_text: str
    span_found: bool
    normalized: str
    claim_type: str
    checkable: bool
    reason_not_checkable: str | None
    entities: list
    dates: list
    numbers: list
    attribution: str | None
    location: str | None
    topic: str | None
    queries: list
    verdict: str | None
    evidence_strength: str | None
    verdict_reason: str | None
    missing_context: str | None
    conflict_note: str | None
    what_would_change: str | None
    weights: dict
    evidence: list[EvidenceOut]


class FindingOut(ORM):
    id: uuid.UUID
    category: str
    check: str
    title: str
    detail: str
    location: dict | None


class HarmSignalOut(BaseModel):
    category: str
    severity: str
    title: str
    detail: str
    evidence: list[str]


class HarmOut(BaseModel):
    level: str
    signals: list[HarmSignalOut]


class JobDetail(JobSummary):
    input_text: str
    conversation_id: uuid.UUID
    explanation: dict | None
    harm: HarmOut | None
    content_meta: dict | None
    models_used: list
    usage: dict
    claims: list[ClaimOut]
    sources: list[SourceOut]
    findings: list[FindingOut]
    events: list[EventOut]


class VerifyRequest(BaseModel):
    retry: bool = False
    language: Language = "en"


class CorrectionRequest(BaseModel):
    relationship: Literal["elder", "friend", "colleague", "group_admin", "other"] = "friend"
    channel: Literal["private", "group"] = "private"
    language: Language = "en"
    tone: Literal["gentle", "respectful", "neutral", "direct", "formal"] = "respectful"


class SourceLink(BaseModel):
    label: str
    url: str
    publisher: str


class CorrectionOut(ORM):
    id: uuid.UUID
    job_id: uuid.UUID
    text: str
    generator: str
    validation: dict
    language: str
    tone: str
    relationship_to: str
    channel: str
    created_at: datetime
    links: list[SourceLink] = []


class HistoryItem(BaseModel):
    job: JobSummary
    conversation_id: uuid.UUID
    conversation_title: str
    message_preview: str
    claim_count: int


class Preferences(BaseModel):
    language: Language = "en"
    theme: Literal["system", "light", "dark"] = "system"
    explanation_language: Language | None = None


class ProviderStatus(BaseModel):
    configured: bool
    detail: str


class Capabilities(BaseModel):
    live_verification: bool
    providers: dict[str, ProviderStatus]
    modalities: dict[str, ProviderStatus]
    languages: list[str]
    limits: dict[str, int]
    retention_days: int
    data_use_notice: str


class UsageRow(BaseModel):
    provider: str
    day: str
    requests: int
    units: int
    errors: int


class UsageOut(BaseModel):
    today: list[UsageRow]
    limits: dict[str, int]
