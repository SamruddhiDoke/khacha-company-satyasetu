"""Explanation generation. Verdicts are fixed before this stage; the model only
puts them into words. Output is validated: claim indices must exist, source
labels must refer to real sources, and URLs are stripped. If the model call
fails, a deterministic template built from the same structured data is used
and labelled as such."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from app.config import LANGUAGE_NAMES
from app.pipeline.llm_io import SYSTEM_EXPLAIN, Explanation, wrap
from app.providers.errors import ProviderError
from app.providers.llm import CallStats, LLMProvider

VERDICT_LABELS = {
    "en": {"verified": "Verified", "false": "False", "partly_true": "Partly true", "misleading": "Misleading",
           "outdated": "Outdated", "conflicting": "Conflicting evidence", "insufficient_evidence": "Insufficient evidence",
           "not_checkable": "Not checkable", "mixed": "Mixed findings"},
    "hi": {"verified": "पुष्ट", "false": "गलत", "partly_true": "आंशिक रूप से सही", "misleading": "भ्रामक",
           "outdated": "पुरानी जानकारी", "conflicting": "विरोधाभासी साक्ष्य", "insufficient_evidence": "अपर्याप्त साक्ष्य",
           "not_checkable": "जाँच योग्य नहीं", "mixed": "मिले-जुले निष्कर्ष"},
    "mr": {"verified": "पुष्टी झाली", "false": "खोटे", "partly_true": "अंशतः खरे", "misleading": "दिशाभूल करणारे",
           "outdated": "जुनी माहिती", "conflicting": "परस्परविरोधी पुरावे", "insufficient_evidence": "अपुरे पुरावे",
           "not_checkable": "तपासता येत नाही", "mixed": "संमिश्र निष्कर्ष"},
}
URL_RX = re.compile(r"https?://\S+")


@dataclass
class ClaimForExplanation:
    index: int
    claim: str
    verdict: str
    reason: str
    quotes: list[tuple[str, str, str]]  # (source label, stance, quote)
    missing_context: str | None
    what_would_change: str | None


def _payload(claims: list[ClaimForExplanation], overall: str, sources: dict[str, str]) -> str:
    lines = [f"Overall verdict (fixed): {overall}", "Sources:"]
    lines += [f"  [{label}] {pub}" for label, pub in sources.items()]
    for c in claims:
        lines.append(f"\nClaim {c.index}: {c.claim}\n  Verdict (fixed): {c.verdict} - {c.reason}")
        for label, stance, quote in c.quotes:
            lines.append(f"  [{label}] {stance}: \"{quote}\"")
        if not c.quotes:
            lines.append("  No validated evidence quotes.")
        if c.missing_context:
            lines.append(f"  Missing context noted by evidence: {c.missing_context}")
        if c.what_would_change:
            lines.append(f"  What could change this: {c.what_would_change}")
    return "\n".join(lines)


def _clean(text: str, valid_labels: set[str]) -> str:
    text = URL_RX.sub("", text)
    return re.sub(r"\[(S\d+)\]", lambda m: m.group(0) if m.group(1) in valid_labels else "", text).strip()


async def explain(llm: LLMProvider, claims: list[ClaimForExplanation], overall: str, sources: dict[str, str],
                  language: str, stats: CallStats) -> dict:
    lang_name = LANGUAGE_NAMES.get(language, "English")
    try:
        out = await llm.generate_json(
            system=SYSTEM_EXPLAIN.format(language=lang_name),
            prompt=wrap("untrusted_findings", _payload(claims, overall, sources)),
            out=Explanation, stats=stats,
        )
        valid_idx = {c.index for c in claims}
        labels = set(sources)
        per_claim = {pc.claim_index: _clean(pc.explanation, labels) for pc in out.per_claim if pc.claim_index in valid_idx}
        if not out.summary.strip():
            raise ValueError("empty summary")
        return {
            "source": "model",
            "language": language,
            "summary": _clean(out.summary, labels),
            "per_claim": per_claim,
            "uncertainty": _clean(out.uncertainty, labels),
            "missing_context": _clean(out.missing_context, labels) if out.missing_context else None,
            "what_would_change": _clean(out.what_would_change, labels),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
    except (ProviderError, ValueError) as e:
        result = template_explanation(claims, overall, sources)
        result["fallback_reason"] = getattr(e, "code", "invalid_output")
        return result


def template_explanation(claims: list[ClaimForExplanation], overall: str, sources: dict[str, str]) -> dict:
    labels = VERDICT_LABELS["en"]
    checkable = [c for c in claims if c.verdict != "not_checkable"]
    counts: dict[str, int] = {}
    for c in checkable:
        counts[c.verdict] = counts.get(c.verdict, 0) + 1
    parts = ", ".join(f"{n} {labels[v].lower()}" for v, n in counts.items())
    summary = (f"SatyaSetu found {len(claims)} statement(s), {len(checkable)} of them checkable. "
               f"Findings: {parts or 'none'}. Overall: {labels[overall]}.")
    per_claim = {}
    for c in claims:
        cited = sorted({label for label, _, _ in c.quotes})
        per_claim[c.index] = f"{labels[c.verdict]}. {c.reason}" + (f" Sources: {', '.join(f'[{x}]' for x in cited)}." if cited else "")
    return {
        "source": "template",
        "language": "en",
        "summary": summary,
        "per_claim": per_claim,
        "uncertainty": "This summary was generated from the structured findings without the language model.",
        "missing_context": next((c.missing_context for c in claims if c.missing_context), None),
        "what_would_change": next((c.what_would_change for c in claims if c.what_would_change),
                                  "Primary sources directly addressing the claim."),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
