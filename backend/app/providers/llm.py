"""LLM provider adapter. The pipeline depends only on `LLMProvider`; Gemini is
one implementation. Every response is validated against a Pydantic model -
anything that does not validate is rejected, never patched up with invented data."""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any, Protocol, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.config import Settings
from app.core import usage
from app.providers.errors import (
    ContentBlocked,
    InvalidModelOutput,
    LocalBudgetExhausted,
    ProviderError,
    ProviderNotConfigured,
    ProviderTimeout,
    QuotaExhausted,
    RateLimited,
)

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


@dataclass
class CallStats:
    """Accumulates which models were used and how many tokens a check consumed."""

    models: list[str] = field(default_factory=list)
    llm_calls: int = 0
    tokens: int = 0
    searches: int = 0
    fetches: int = 0

    def as_dict(self) -> dict:
        return {"llm_calls": self.llm_calls, "tokens": self.tokens, "searches": self.searches, "fetches": self.fetches}


class LLMProvider(Protocol):
    name: str

    async def generate_json(self, *, system: str, prompt: str, out: type[T], stats: CallStats) -> T: ...


# ---------------------------------------------------------------------------
# Pydantic JSON schema -> Gemini responseSchema (OpenAPI 3.0 subset)
# ---------------------------------------------------------------------------
_TYPE_MAP = {"string": "STRING", "integer": "INTEGER", "number": "NUMBER", "boolean": "BOOLEAN",
             "array": "ARRAY", "object": "OBJECT"}


def to_gemini_schema(model: type[BaseModel]) -> dict:
    raw = model.model_json_schema()
    defs = raw.get("$defs", {})

    def conv(node: dict) -> dict:
        if "$ref" in node:
            return conv(defs[node["$ref"].split("/")[-1]])
        if "anyOf" in node:
            options = [o for o in node["anyOf"] if o.get("type") != "null"]
            out = conv(options[0])
            if len(options) < len(node["anyOf"]):
                out["nullable"] = True
            return out
        if "enum" in node or "const" in node:
            values = node.get("enum") or [node["const"]]
            return {"type": "STRING", "enum": [str(v) for v in values]}
        t = node.get("type", "string")
        out: dict[str, Any] = {"type": _TYPE_MAP[t]}
        if node.get("description"):
            out["description"] = node["description"]
        if t == "array":
            out["items"] = conv(node.get("items", {"type": "string"}))
        if t == "object":
            props = node.get("properties", {})
            out["properties"] = {k: conv(v) for k, v in props.items()}
            out["required"] = node.get("required", list(props))
            out["propertyOrdering"] = list(props)
        return out

    return conv(raw)


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"


class GeminiProvider:
    name = "gemini"

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        if not settings.gemini_configured:
            raise ProviderNotConfigured("GEMINI_API_KEY is not set", provider="gemini")
        self._key = settings.gemini_api_key.get_secret_value().strip()  # type: ignore[union-attr]
        self.settings = settings
        self.models = [m for m in (settings.gemini_model, settings.gemini_fallback_model) if m]
        self._client = client or httpx.AsyncClient(timeout=settings.gemini_timeout_s)
        self._limiter = usage.MinuteLimiter(settings.gemini_max_requests_per_minute, "gemini")
        # model -> UTC instant when its daily quota resets. Exhausted models are skipped until then, so a
        # fallback call does not first spend a request and a rate-limit slot on a model that will refuse it.
        self._exhausted_until: dict[str, datetime] = {}

    def next_quota_reset(self, now: datetime | None = None) -> datetime:
        """Gemini RPD quotas reset at midnight Pacific time (configurable via GEMINI_QUOTA_RESET_TZ)."""
        now = now or datetime.now(timezone.utc)
        tz = ZoneInfo(self.settings.gemini_quota_reset_tz)
        local = now.astimezone(tz)
        midnight = datetime(local.year, local.month, local.day, tzinfo=tz) + timedelta(days=1)
        return midnight.astimezone(timezone.utc)

    def available_models(self, now: datetime | None = None) -> list[str]:
        now = now or datetime.now(timezone.utc)
        return [m for m in self.models if self._exhausted_until.get(m, now) <= now]

    async def check_model(self, model: str) -> tuple[bool, str]:
        """models.get is a metadata call - it consumes no generation quota."""
        try:
            r = await self._client.get(f"{GEMINI_BASE}/models/{model}", headers={"x-goog-api-key": self._key})
        except httpx.HTTPError as e:
            return False, f"network error: {type(e).__name__}"
        if r.status_code == 200:
            return True, "available"
        return False, f"HTTP {r.status_code}: {_error_message(r)}"

    async def generate_json(self, *, system: str, prompt: str, out: type[T], stats: CallStats) -> T:
        schema = to_gemini_schema(out)
        last_err: ProviderError | None = None
        models = self.available_models()
        if not models:
            reset = min(self._exhausted_until.values())
            raise QuotaExhausted(
                f"Gemini free-tier daily quota is exhausted for all configured models until "
                f"{reset:%Y-%m-%d %H:%M} UTC.", provider="gemini")
        for model in models:
            try:
                return await self._generate_with_model(model, system, prompt, out, schema, stats)
            except LocalBudgetExhausted:
                raise  # our own provider-wide budget: no model should be marked exhausted
            except QuotaExhausted as e:
                self._exhausted_until[model] = self.next_quota_reset()
                log.warning("gemini model %s daily quota exhausted; skipping it until %s UTC",
                            model, f"{self._exhausted_until[model]:%Y-%m-%d %H:%M}")
                last_err = e
            except (_ModelUnavailable, ProviderTimeout) as e:
                log.warning("gemini model %s unavailable (%s); trying fallback if configured", model, e)
                last_err = e
        assert last_err is not None
        if isinstance(last_err, _ModelUnavailable):
            raise ProviderError(f"No configured Gemini model is available to this API key: {last_err}", provider="gemini")
        raise last_err

    async def _generate_with_model(self, model, system, prompt, out: type[T], schema, stats: CallStats) -> T:
        contents = [{"role": "user", "parts": [{"text": prompt}]}]
        validation_retry_used = False
        transient_retry_used = False
        while True:
            data = await self._post(model, system, contents, schema, stats, allow_retry=not transient_retry_used)
            transient_retry_used = True
            text = _extract_text(data)
            try:
                parsed = out.model_validate(json.loads(text))
                if model not in stats.models:
                    stats.models.append(model)
                return parsed
            except (json.JSONDecodeError, ValidationError) as e:
                log.warning("gemini returned output that failed validation: %s", str(e)[:300])
                if validation_retry_used:
                    raise InvalidModelOutput(
                        "The language model returned output that did not match the required structure twice.",
                        provider="gemini",
                    ) from e
                validation_retry_used = True
                contents = contents + [
                    {"role": "model", "parts": [{"text": text[:4000]}]},
                    {"role": "user", "parts": [{"text": "That response did not validate against the schema "
                                                          f"({str(e)[:500]}). Return corrected JSON only."}]},
                ]

    async def _post(self, model, system, contents, schema, stats: CallStats, allow_retry: bool) -> dict:
        gen_config: dict[str, Any] = {"responseMimeType": "application/json", "responseSchema": schema}
        if model.startswith("gemini-3") and self.settings.gemini_thinking_level:
            gen_config["thinkingConfig"] = {"thinkingLevel": self.settings.gemini_thinking_level}
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": contents,
            "generationConfig": gen_config,
        }
        attempts = 2 if allow_retry else 1
        for attempt in range(attempts):
            await usage.ensure_daily_budget("gemini", self.settings.gemini_max_requests_per_day)
            await self._limiter.acquire()
            try:
                r = await self._client.post(
                    f"{GEMINI_BASE}/models/{model}:generateContent",
                    headers={"x-goog-api-key": self._key, "Content-Type": "application/json"},
                    json=body,
                )
            except httpx.TimeoutException as e:
                await usage.record("gemini", errors=1)
                raise ProviderTimeout("The language model did not respond in time.", provider="gemini", retryable=True) from e
            except httpx.HTTPError as e:
                await usage.record("gemini", errors=1)
                raise ProviderError(f"Network error contacting Gemini: {type(e).__name__}", provider="gemini", retryable=True) from e

            stats.llm_calls += 1
            if r.status_code == 200:
                data = r.json()
                tokens = int(data.get("usageMetadata", {}).get("totalTokenCount", 0) or 0)
                stats.tokens += tokens
                await usage.record("gemini", units=tokens)
                return data

            await usage.record("gemini", errors=1)
            msg = _error_message(r)
            if r.status_code == 429:
                if _is_daily_quota(r):
                    self._limiter.release()  # refused without doing work: don't let it crowd out the fallback
                    raise QuotaExhausted(f"Gemini free-tier daily quota exhausted for {model}.", provider="gemini")
                delay = _retry_delay(r)
                if attempt + 1 < attempts and delay <= 20:
                    await asyncio.sleep(delay)
                    continue
                raise RateLimited("Gemini rate limit reached. Please retry in a minute.", provider="gemini", retryable=True)
            if r.status_code == 404 or (r.status_code == 400 and "model" in msg.lower() and "not" in msg.lower()):
                raise _ModelUnavailable(f"{model}: {msg}")
            if r.status_code in (401, 403):
                raise ProviderError(f"Gemini rejected the API key or access: {msg}", provider="gemini")
            if r.status_code >= 500 and attempt + 1 < attempts:
                await asyncio.sleep(2)
                continue
            raise ProviderError(f"Gemini error HTTP {r.status_code}: {msg}", provider="gemini", retryable=r.status_code >= 500)
        raise ProviderError("Gemini request failed", provider="gemini", retryable=True)


class _ModelUnavailable(ProviderError):
    code = "provider_error"


def _extract_text(data: dict) -> str:
    feedback = data.get("promptFeedback") or {}
    if feedback.get("blockReason"):
        raise ContentBlocked(f"The model provider blocked this content ({feedback['blockReason']}).", provider="gemini")
    candidates = data.get("candidates") or []
    if not candidates:
        raise InvalidModelOutput("The model returned no candidates.", provider="gemini")
    cand = candidates[0]
    reason = cand.get("finishReason")
    if reason in ("SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII"):
        raise ContentBlocked(f"The model provider blocked the response ({reason}).", provider="gemini")
    parts = (cand.get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    if not text.strip():
        raise InvalidModelOutput(f"The model returned an empty response (finishReason={reason}).", provider="gemini")
    return text


def _error_message(r: httpx.Response) -> str:
    try:
        return str(r.json().get("error", {}).get("message", ""))[:300]
    except Exception:
        return r.text[:300]


def _details(r: httpx.Response) -> list[dict]:
    try:
        return r.json().get("error", {}).get("details", []) or []
    except Exception:
        return []


def _is_daily_quota(r: httpx.Response) -> bool:
    for d in _details(r):
        for v in d.get("violations", []) or []:
            if "PerDay" in str(v.get("quotaId", "")) or "per_day" in str(v.get("quotaMetric", "")).lower():
                return True
    return False


def _retry_delay(r: httpx.Response) -> float:
    for d in _details(r):
        if str(d.get("@type", "")).endswith("RetryInfo"):
            raw = str(d.get("retryDelay", "")).rstrip("s")
            try:
                return float(raw)
            except ValueError:
                pass
    return 30.0
