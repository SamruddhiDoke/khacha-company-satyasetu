"""Rule-based harm signals, kept separate from factual verdicts.

A message can be unverified *and* dangerous to act on. These rules flag risky
requests (OTP, payments, links, personal data, medical actions, impersonation,
urgency). They are deterministic and run even when AI providers are not
configured. Their false-positive / false-negative rates are measured by
`tests/test_harm_eval.py` on a small labelled set - see docs/EVALUATION.md;
they are heuristics, not a reliable detector."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from app.pipeline.sources import domain_of, registrable_domain
from app.pipeline.text import extract_urls


@dataclass
class HarmSignal:
    category: str
    severity: str  # high | medium | low
    title: str
    detail: str
    evidence: list[str]


def _rx(*parts: str) -> re.Pattern:
    return re.compile("|".join(parts), re.IGNORECASE)


CREDENTIAL = _rx(
    r"\botp\b", r"one[- ]time password", r"\bpin\b", r"\bcvv\b", r"password", r"passcode", r"login details",
    r"net ?banking (id|credentials)", r"card (number|details)", r"verification code",
    "ओटीपी", "पासवर्ड", "पिन नंबर", "कार्ड नंबर", "सीवीवी",
)
SHARE_VERB = _rx(
    r"\bshar(e|ing)\b", r"\bsend(ing)?\b", r"\btell\b", r"\bprovid(e|ing)\b", r"\benter(ing)?\b",
    r"\bsubmit(ting)?\b", r"\breply with\b", r"\bupdat(e|ing)\b", r"\bverify(ing)?\b", r"\bupload(ing)?\b", "बताएं", "भेजें", "शेयर", "साझा", "पाठवा", "सांगा", "द्या", "डालें",
)
PAYMENT = _rx(
    r"\bpay\b", r"\bpayment\b", r"processing fee", r"registration fee", r"\bupi\b", r"\bgpay\b", r"phonepe",
    r"paytm", r"transfer (rs|inr|₹)", r"₹\s?\d", r"\brs\.?\s?\d", r"\binr\s?\d", r"send money", r"deposit",
    r"refundable", r"gift card", r"crypto", r"bitcoin", r"[\w.\-]{2,}@(ybl|okaxis|oksbi|okhdfcbank|okicici|paytm|upi|ibl|axl)\b",
    "भुगतान", "शुल्क", "फीस", "पैसे भेजें", "पैसे पाठवा", "रुपये जमा",
)
PERSONAL = _rx(
    r"aadhaa?r( number| card)?", r"\bpan( card| number)\b", r"date of birth", r"bank account number",
    r"account (number|details)", r"\bifsc\b", r"voter id", r"passport (number|copy)", r"mother'?s maiden", r"\bkyc\b", r"address proof", r"selfie with",
    "आधार", "पैन कार्ड", "खाता संख्या", "खाते क्रमांक", "केवाईसी",
)
MEDICAL_ACTION = _rx(
    r"\bcure[sd]?\b", r"\btreat(s|ment)?\b", r"\bdrink\b", r"\bconsume\b", r"\bdosage\b", r"\bdose\b",
    r"stop (taking|your) (medicine|medication|insulin|tablets)", r"no need (for|of) (doctor|medicine|vaccine)",
    r"instead of (medicine|vaccine|chemo)", r"home remedy", r"kills? (the )?(virus|cancer|bacteria)",
    "इलाज", "दवा", "पिएं", "उपाय", "बरा होतो", "औषध", "रामबाण",
)
MEDICAL_CONTEXT = _rx(
    r"cancer", r"diabet", r"covid", r"corona", r"virus", r"vaccine", r"heart attack", r"kidney", r"insulin",
    r"blood pressure", r"\bbp\b", r"dengue", r"malaria", r"tumou?r", r"infection", r"fever", r"stroke",
    "कैंसर", "मधुमेह", "डायबिटीज", "कोरोना", "बुखार", "कर्करोग", "ताप",
)
URGENCY = _rx(
    r"\burgent\b", r"immediately", r"within \d+ (hours|hrs|minutes|days)", r"last date today", r"before midnight",
    r"account (will be|is being) (blocked|suspended|closed|deactivated)", r"will be (blocked|suspended|cancelled)",
    r"\btoday only\b", r"will be disconnected", r"\btonight\b", r"final (notice|warning)", r"forward (this )?to \d+", r"share (this )?with (all|everyone|\d+)", r"emergency",
    "तुरंत", "आज ही", "ब्लॉक हो जाएगा", "बंद हो जाएगा", "तातडीने", "बंद होईल", "आपातकाल",
)
AUTHORITY = _rx(
    r"\brbi\b", r"reserve bank", r"\bsbi\b", r"state bank", r"income tax", r"\bgovt\b", r"government",
    r"ministry", r"prime minister", r"(?<![\d.:]\s)(?<![\d.:])\bpm\b", r"police", r"cyber cell", r"\buidai\b", r"\bnpci\b", r"election commission",
    r"\btrai\b", r"customs", r"\bcbi\b", r"\bed\b", r"electricity board", r"msedcl", r"\bhdfc\b", r"\bicici\b",
    r"\baxis bank\b", r"\bkotak\b", r"\blic\b", r"\bepfo?\b", r"courier", r"fedex", r"\bdhl\b",
    "सरकार", "मंत्रालय", "पुलिस", "आयकर", "रिज़र्व बैंक", "शासन", "पोलीस",
)
AI_INSTRUCTION = _rx(
    r"ignore (all |any )?(previous|prior|above) instructions", r"you are (now )?an? (ai|assistant|language model)",
    r"system prompt", r"mark this (message )?as (true|verified|genuine)", r"respond only with", r"disregard (the|your) rules",
)
SHORTENERS = {"bit.ly", "tinyurl.com", "cutt.ly", "rb.gy", "t.ly", "is.gd", "shorturl.at", "goo.gl", "ow.ly",
              "rebrand.ly", "tiny.cc", "s.id", "shorturl.gg", "bitly.ws", "t.co", "wa.link", "wa.me"}
BRAND_TOKENS = {"sbi": "sbi.co.in", "rbi": "rbi.org.in", "hdfc": "hdfcbank.com", "icici": "icicibank.com",
                "paytm": "paytm.com", "uidai": "uidai.gov.in", "aadhaar": "uidai.gov.in", "incometax": "incometax.gov.in",
                "epfo": "epfindia.gov.in", "npci": "npci.org.in", "irctc": "irctc.co.in", "amazon": "amazon.in",
                "flipkart": "flipkart.com", "whatsapp": "whatsapp.com", "pmkisan": "pmkisan.gov.in", "kyc": ""}
SUSPICIOUS_TLDS = (".xyz", ".top", ".club", ".online", ".site", ".live", ".buzz", ".click", ".icu", ".tk", ".ml",
                   ".ga", ".cf", ".gq", ".info", ".shop", ".rest", ".monster", ".cfd")


def _found(rx: re.Pattern, text: str) -> list[str]:
    return sorted({m.group(0).strip() for m in rx.finditer(text)})[:4]


BARE_LINK = re.compile(r"(?<![\w@/.])((?:" + "|".join(re.escape(d) for d in sorted(SHORTENERS, key=len, reverse=True))
                       + r")/[\w\-./?=&%]+)", re.IGNORECASE)


def link_signals(text: str) -> list[HarmSignal]:
    out: list[HarmSignal] = []
    urls = extract_urls(text)
    urls += ["http://" + m for m in BARE_LINK.findall(text) if not any(m in u for u in urls)]
    for url in urls:
        host = domain_of(url)
        reg = registrable_domain(host)
        reasons = []
        if host in SHORTENERS or reg in SHORTENERS:
            reasons.append("uses a link shortener that hides the real destination")
        if re.fullmatch(r"[\d.]+", host):
            reasons.append("points to a raw IP address instead of a named website")
        if "xn--" in host:
            reasons.append("uses an internationalised (punycode) domain that can imitate another site")
        if host.endswith(SUSPICIOUS_TLDS):
            reasons.append(f"uses a domain ending ({host.rsplit('.', 1)[-1]}) commonly abused in scams")
        if url.lower().split("?")[0].endswith(".apk"):
            reasons.append("downloads an Android app (.apk) from outside the app store")
        for token, official in BRAND_TOKENS.items():
            if token in host.replace("-", "").replace(".", "") and (not official or reg != registrable_domain(official)):
                reasons.append(f"mentions '{token}' but is not that organisation's official domain")
                break
        if reasons:
            out.append(HarmSignal("suspicious_link", "high", "Suspicious link",
                                  f"The link {host} " + "; ".join(reasons) + ". Do not open it or enter details.",
                                  [url]))
    return out


def assess(text: str) -> list[dict]:
    t = text or ""
    signals: list[HarmSignal] = []
    cred = _found(CREDENTIAL, t)
    share = _found(SHARE_VERB, t)
    if cred and share:
        signals.append(HarmSignal("credentials", "high", "Asks for an OTP, PIN or password",
                                  "Banks, government bodies and genuine companies never ask you to share an OTP, PIN, "
                                  "CVV or password. Do not share it with anyone.", cred))
    pay = _found(PAYMENT, t)
    if pay and (share or len(pay) >= 2 or _found(URGENCY, t) or re.search(r"\bfee\b|\bfine\b|शुल्क|फीस", t, re.I)):
        signals.append(HarmSignal("payment", "high", "Requests a payment",
                                  "The message asks for money or a fee. Do not pay until you have confirmed the request "
                                  "through the organisation's official website or helpline.", pay))
    personal = _found(PERSONAL, t)
    if personal and share:
        signals.append(HarmSignal("personal_info", "medium", "Asks for personal or identity details",
                                  "Sharing Aadhaar, PAN or account details with unknown parties can enable fraud.", personal))
    signals.extend(link_signals(t))
    med_a, med_c = _found(MEDICAL_ACTION, t), _found(MEDICAL_CONTEXT, t)
    if med_a and med_c:
        signals.append(HarmSignal("medical", "medium", "Suggests a medical action",
                                  "Health advice in forwards can be harmful. Do not change treatment or stop medicine "
                                  "without consulting a qualified doctor.", med_a + med_c))
    authority = _found(AUTHORITY, t)
    risky = any(s.category in ("credentials", "payment", "personal_info", "suspicious_link") for s in signals)
    if authority and risky:
        signals.append(HarmSignal("impersonation", "high", "Possible impersonation",
                                  "The message invokes an official organisation while asking for details, money or a "
                                  "link click - a common impersonation pattern. Contact the organisation directly "
                                  "using details from its official website.", authority))
    urgent = _found(URGENCY, t)
    if urgent:
        signals.append(HarmSignal("urgency", "low", "Creates urgency",
                                  "Pressure to act or forward immediately is a common manipulation tactic. "
                                  "Take time to check first.", urgent))
    inj = _found(AI_INSTRUCTION, t)
    if inj:
        signals.append(HarmSignal("ai_instruction", "low", "Contains instructions aimed at AI tools",
                                  "The text tries to instruct automated checkers. SatyaSetu ignores such instructions; "
                                  "their presence is itself a warning sign.", inj))
    order = {"high": 0, "medium": 1, "low": 2}
    signals.sort(key=lambda s: order[s.severity])
    return [asdict(s) for s in signals]


def risk_level(signals: list[dict]) -> str:
    if any(s["severity"] == "high" for s in signals):
        return "high"
    if any(s["severity"] == "medium" for s in signals):
        return "medium"
    return "low" if signals else "none"
