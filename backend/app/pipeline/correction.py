"""Correction-message drafting, validated against the verification evidence.

Validation rules (a draft that fails is regenerated once, then replaced by a
template built only from the findings):
  - stated_verdict must equal the job's overall verdict;
  - every number in the draft must appear in the original message, the claims
    or the validated quotes (blocks invented statistics);
  - no URLs in the model text (links are appended from the real source list);
  - for insufficient/conflicting/not_checkable results the draft must not call
    the message false.
"""
from __future__ import annotations

import re

from app.config import LANGUAGE_NAMES
from app.models import VerificationJob
from app.pipeline.explain import VERDICT_LABELS
from app.pipeline.llm_io import SYSTEM_CORRECT, CorrectionDraft, wrap
from app.providers.errors import ProviderError
from app.providers.llm import CallStats, LLMProvider

NUM_RX = re.compile(r"\d[\d,.]*")
URL_RX = re.compile(r"https?://\S+|www\.\S+")
FALSE_WORDS = re.compile(r"\b(false|fake|hoax|untrue|lie)\b|गलत|झूठ|फर्जी|खोटे|खोटी|बनावट", re.I)
HEDGE_VERDICTS = ("insufficient_evidence", "conflicting", "not_checkable")
RELATIONSHIP = {"elder": "a parent or elder relative", "friend": "a friend", "colleague": "a colleague",
                "group_admin": "a group administrator", "other": "an acquaintance"}


def _corpus(job: VerificationJob) -> str:
    parts = [job.input_text]
    for c in job.claims:
        parts += [c.original_text, c.normalized]
        parts += [e.quote or "" for e in c.evidence if e.counted]
    return " ".join(parts)


def _nums(s: str) -> set[str]:
    return {n.strip(".,").replace(",", "") for n in NUM_RX.findall(s) if n.strip(".,")}


def findings_text(job: VerificationJob, labels: dict[str, str]) -> str:
    lines = [f"Overall verdict: {job.overall_verdict}"]
    src_by_id = {s.id: s for s in job.sources}
    for c in job.claims:
        lines.append(f"- Claim: {c.normalized} -> {c.verdict} ({c.verdict_reason})")
        for e in c.evidence:
            if e.counted:
                s = src_by_id.get(e.source_id)
                pub = (s.publisher or s.domain) if s else "source"
                lines.append(f"    {e.stance} per {pub}: \"{e.quote}\"")
        if c.missing_context:
            lines.append(f"    Missing context: {c.missing_context}")
    return "\n".join(lines)


def validate(draft: CorrectionDraft, job: VerificationJob) -> list[str]:
    problems = []
    if draft.stated_verdict.strip().lower() != (job.overall_verdict or "").lower():
        problems.append("stated verdict does not match the verification result")
    unknown = _nums(draft.message) - _nums(_corpus(job))
    if unknown:
        problems.append(f"contains numbers not present in the evidence: {', '.join(sorted(unknown)[:5])}")
    if URL_RX.search(draft.message):
        problems.append("contains a URL written by the model")
    if job.overall_verdict in HEDGE_VERDICTS and FALSE_WORDS.search(draft.message):
        problems.append("calls the message false although the evidence was inconclusive")
    if len(draft.message) > 1200:
        problems.append("too long")
    return problems


async def draft_correction(llm: LLMProvider | None, job: VerificationJob, relationship: str, channel: str,
                           language: str, tone: str, stats: CallStats) -> tuple[str, str, dict]:
    labels: dict[str, str] = (job.explanation or {}).get("source_labels", {})
    attempts: list[dict] = []
    if llm is not None:
        prompt = (wrap("untrusted_original_message", job.input_text[:2500]) + "\n\n" +
                  wrap("untrusted_findings", findings_text(job, labels)))
        for _ in range(2):
            try:
                draft = await llm.generate_json(
                    system=SYSTEM_CORRECT.format(language=LANGUAGE_NAMES[language], relationship=RELATIONSHIP[relationship],
                                                 channel=channel, tone=tone),
                    prompt=prompt + ("\n\nYour previous draft was rejected: " + "; ".join(attempts[-1]["problems"])
                                     if attempts else ""),
                    out=CorrectionDraft, stats=stats)
            except ProviderError as e:
                attempts.append({"problems": [f"provider error: {e.code}"]})
                break
            problems = validate(draft, job)
            if not problems:
                return draft.message.strip(), f"model:{','.join(stats.models) or 'llm'}", {
                    "passed": True, "checks": ["verdict_match", "numbers_in_evidence", "no_model_urls", "hedging"],
                    "rejected_drafts": len(attempts)}
            attempts.append({"problems": problems})
    text = template_correction(job, language, tone)
    return text, "template", {"passed": True, "checks": ["template_from_findings"], "rejected_drafts": len(attempts),
                              "fallback_reasons": [p for a in attempts for p in a["problems"]]}


TEMPLATES = {
    "en": {
        "open": {"gentle": "Hi, I looked into the message you shared.", "respectful": "Namaste, I checked the message you shared.",
                 "neutral": "I checked the forwarded message.", "direct": "I checked this forward.",
                 "formal": "I have reviewed the forwarded message."},
        "verified": "The sources I found support it.",
        "false": "Credible sources contradict it, so please don't forward it further.",
        "hedge": "I could not confirm it from reliable sources, so it may be better not to forward it until it is confirmed.",
        "mixed": "Some parts are supported by sources, but others are not.",
        "context": "It leaves out important context, so it can give the wrong impression.",
        "outdated": "The information appears to be outdated.",
        "close": "Independent check using SatyaSetu.",
    },
    "hi": {
        "open": {"gentle": "नमस्ते, आपने जो संदेश भेजा था, मैंने उसकी जाँच की।", "respectful": "नमस्ते, आपके भेजे संदेश की मैंने जाँच की।",
                 "neutral": "मैंने इस फॉरवर्ड संदेश की जाँच की।", "direct": "मैंने यह फॉरवर्ड जाँचा।",
                 "formal": "मैंने भेजे गए संदेश की समीक्षा की है।"},
        "verified": "मिले स्रोत इसकी पुष्टि करते हैं।",
        "false": "विश्वसनीय स्रोत इसका खंडन करते हैं, कृपया इसे आगे न भेजें।",
        "hedge": "विश्वसनीय स्रोतों से इसकी पुष्टि नहीं हो सकी, इसलिए पुष्टि होने तक इसे आगे न भेजना बेहतर होगा।",
        "mixed": "कुछ बातें स्रोतों से मेल खाती हैं, पर कुछ नहीं।",
        "context": "इसमें ज़रूरी संदर्भ छूटा है, जिससे गलत धारणा बन सकती है।",
        "outdated": "यह जानकारी पुरानी लगती है।",
        "close": "SatyaSetu द्वारा स्वतंत्र जाँच।",
    },
    "mr": {
        "open": {"gentle": "नमस्कार, तुम्ही पाठवलेला संदेश मी तपासला.", "respectful": "नमस्कार, तुम्ही पाठवलेल्या संदेशाची मी तपासणी केली.",
                 "neutral": "मी हा फॉरवर्ड संदेश तपासला.", "direct": "मी हा फॉरवर्ड तपासला.",
                 "formal": "मी पाठवलेल्या संदेशाचे पुनरावलोकन केले आहे."},
        "verified": "मिळालेले स्रोत याला दुजोरा देतात.",
        "false": "विश्वासार्ह स्रोत याचे खंडन करतात, कृपया हा पुढे पाठवू नका.",
        "hedge": "विश्वासार्ह स्रोतांकडून याची पुष्टी झाली नाही, म्हणून खात्री होईपर्यंत हा पुढे न पाठवणे चांगले.",
        "mixed": "काही भाग स्रोतांशी जुळतात, पण काही नाहीत.",
        "context": "यात महत्त्वाचा संदर्भ सुटलेला आहे, त्यामुळे चुकीचा समज होऊ शकतो.",
        "outdated": "ही माहिती जुनी असल्याचे दिसते.",
        "close": "SatyaSetu द्वारे स्वतंत्र तपासणी.",
    },
}


def template_correction(job: VerificationJob, language: str, tone: str) -> str:
    t = TEMPLATES.get(language, TEMPLATES["en"])
    v = job.overall_verdict or "insufficient_evidence"
    body = {"verified": t["verified"], "false": t["false"], "misleading": t["context"], "partly_true": t["mixed"],
            "mixed": t["mixed"], "outdated": t["outdated"]}.get(v, t["hedge"])
    label = VERDICT_LABELS.get(language, VERDICT_LABELS["en"])[v]
    return f"{t['open'][tone]} {body} ({label})\n{t['close']}"
