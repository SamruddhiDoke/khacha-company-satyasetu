"""Circular / document forensics.

Findings are reported in four separate categories:
  confirmed_inconsistency  - provably wrong inside the document (e.g. 31 Feb, wrong weekday, deadline before issue)
  warning                  - a sign worth caution, NOT proof of fraud (free-mail contact, payment request...)
  could_not_check          - a check we cannot perform with available authoritative data
  passed                   - a check that ran and found no problem
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone

from app.pipeline.harm import PAYMENT, link_signals
from app.pipeline.sources import OFFICIAL_SUFFIXES

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
     "november", "december"], 1)}
MONTHS.update({k[:3]: v for k, v in list(MONTHS.items())})
MONTHS["sept"] = 9
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
WD_RX = r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
MON_RX = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"

NUMERIC_DATE = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{4}|\d{2})\b")
TEXT_DATE = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+{MON_RX}[,.]?\s+(\d{{4}})\b", re.I)
TEXT_DATE_US = re.compile(rf"\b{MON_RX}\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", re.I)
ISSUE_HINT = re.compile(r"(dated|date of issue|issue date|issued on|^\s*date\s*[:\-])", re.I | re.M)
DEADLINE_HINT = re.compile(r"(last date|deadline|on or before|before|latest by|due date|valid till|closing date)", re.I)
EMAIL = re.compile(r"\b[\w.+-]+@([\w-]+\.)+[a-z]{2,}\b", re.I)
FREE_MAIL = ("gmail.com", "yahoo.com", "yahoo.co.in", "outlook.com", "hotmail.com", "rediffmail.com", "proton.me",
             "protonmail.com", "aol.com", "ymail.com")
OFFICIAL_CLAIM = re.compile(r"government of|govt\.? of|ministry of|department of|reserve bank|board of|university|"
                            r"commission|municipal|collector|directorate|भारत सरकार|शासन|मंत्रालय|विभाग", re.I)
REF_NO = re.compile(r"\b(ref(?:erence)?\.?\s*no\.?|f\.?\s*no\.?|circular\s*no\.?|letter\s*no\.?|order\s*no\.?|"
                    r"notification\s*no\.?)\s*[:\-]?\s*([A-Z0-9][\w/().\-]{3,60})", re.I)
PHONE = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?!\d)")
EDITORS = ("canva", "picsart", "photoshop", "gimp", "snapseed", "pixlr", "photopea", "ilovepdf edit", "sejda")


@dataclass
class Finding:
    category: str
    check: str
    title: str
    detail: str
    location: dict | None = None


@dataclass
class FoundDate:
    raw: str
    value: date | None
    page: int
    pos: int
    line: str
    weekday_text: str | None
    impossible_reason: str | None


def _line_at(text: str, pos: int) -> str:
    start = text.rfind("\n", 0, pos) + 1
    end = text.find("\n", pos)
    return text[start: end if end != -1 else len(text)].strip()[:200]


def _mk(y: int, m: int, d: int) -> tuple[date | None, str | None]:
    if y < 100:
        y += 2000
    if not 1 <= m <= 12:
        return None, f"month {m} does not exist"
    try:
        return date(y, m, d), None
    except ValueError:
        return None, f"day {d} does not exist in month {m} of {y}"


def find_dates(pages: list[str]) -> list[FoundDate]:
    out: list[FoundDate] = []
    for pi, text in enumerate(pages, 1):
        spans = []
        for m in NUMERIC_DATE.finditer(text):
            d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            spans.append((m, *_mk(y, mo, d)))  # Indian convention: DD/MM/YYYY
        for m in TEXT_DATE.finditer(text):
            mo = MONTHS[m.group(2).lower()[:4] if m.group(2).lower()[:4] == "sept" else m.group(2).lower()[:3]]
            spans.append((m, *_mk(int(m.group(3)), mo, int(m.group(1)))))
        for m in TEXT_DATE_US.finditer(text):
            mo = MONTHS[m.group(1).lower()[:3]]
            spans.append((m, *_mk(int(m.group(3)), mo, int(m.group(2)))))
        for m, value, reason in spans:
            around = text[max(0, m.start() - 15): m.end() + 15].lower()
            wd = re.search(WD_RX, around)
            out.append(FoundDate(m.group(0), value, pi, m.start(), _line_at(text, m.start()),
                                 wd.group(1) if wd else None, reason))
    return out


def analyse(pages: list[str], metadata: dict | None = None, extraction: dict | None = None,
            today: date | None = None) -> list[dict]:
    today = today or datetime.now(timezone.utc).date()
    full = "\n".join(pages)
    findings: list[Finding] = []

    if not full.strip():
        return [asdict(Finding("could_not_check", "text", "No readable text",
                               "No text could be extracted from the document, so no checks were possible."))]

    # 1. Calendar validity and weekdays
    dates = find_dates(pages)
    impossible = [d for d in dates if d.impossible_reason]
    for d in impossible:
        findings.append(Finding("confirmed_inconsistency", "impossible_date", f"Impossible date: {d.raw}",
                                f"The date {d.raw} cannot exist ({d.impossible_reason}).",
                                {"page": d.page, "snippet": d.line}))
    wd_checked = 0
    for d in dates:
        if d.value and d.weekday_text:
            wd_checked += 1
            actual = WEEKDAYS[d.value.weekday()]
            if actual != d.weekday_text:
                findings.append(Finding("confirmed_inconsistency", "weekday_mismatch",
                                        f"Wrong weekday for {d.raw}",
                                        f"The document says {d.weekday_text.title()}, but {d.value.isoformat()} "
                                        f"was a {actual.title()}.", {"page": d.page, "snippet": d.line}))
    valid = [d for d in dates if d.value]
    if dates and not impossible:
        findings.append(Finding("passed", "calendar_dates", "All dates are valid calendar dates",
                                f"{len(dates)} date(s) found; none is impossible."))
    if wd_checked and not any(f.check == "weekday_mismatch" for f in findings):
        findings.append(Finding("passed", "weekdays", "Weekdays match their dates",
                                f"{wd_checked} weekday mention(s) checked."))

    # 2. Issue date vs deadline
    issue = next((d for d in valid if ISSUE_HINT.search(d.line)), None) or (valid[0] if valid else None)
    deadlines = [d for d in valid if DEADLINE_HINT.search(d.line) and d is not issue]
    if issue and deadlines:
        bad = [d for d in deadlines if d.value < issue.value]  # type: ignore[operator]
        for d in bad:
            findings.append(Finding("confirmed_inconsistency", "deadline_before_issue", "Deadline is before the issue date",
                                    f"Deadline {d.raw} is earlier than the issue date {issue.raw}.",
                                    {"page": d.page, "snippet": d.line}))
        if not bad:
            findings.append(Finding("passed", "deadline_order", "Deadlines fall after the issue date",
                                    f"Issue date {issue.raw}; {len(deadlines)} deadline(s) checked."))
    if issue and issue.value and issue.value > today:
        findings.append(Finding("warning", "future_issue_date", "Issue date is in the future",
                                f"The document appears to be dated {issue.raw}, which is after today.",
                                {"page": issue.page, "snippet": issue.line}))
    if not valid:
        findings.append(Finding("could_not_check", "dates", "No dates found", "No recognisable dates were found to check."))

    # 3. Contact details and domains
    claims_official = bool(OFFICIAL_CLAIM.search(full))
    for m in EMAIL.finditer(full):
        dom = m.group(0).split("@", 1)[1].lower()
        if dom in FREE_MAIL and claims_official:
            findings.append(Finding("warning", "free_mail_contact", "Official-looking document uses a free email address",
                                    f"{m.group(0)} is a personal webmail address. Government and institutional "
                                    "circulars normally use official domains. This is a warning sign, not proof.",
                                    {"page": _page_of(pages, m.start()), "snippet": _line_at(full, m.start())}))
        elif dom.endswith(OFFICIAL_SUFFIXES):
            findings.append(Finding("passed", "official_email", "Contact email uses an official domain",
                                    f"{m.group(0)} uses an official-looking domain. This does not by itself prove the "
                                    "document is genuine."))
    for sig in link_signals(full):
        findings.append(Finding("warning", "suspicious_link", sig.title, sig.detail,
                                {"snippet": sig.evidence[0][:200]}))

    # 4. Payment requests
    pay = list(PAYMENT.finditer(full))
    if pay:
        m = pay[0]
        findings.append(Finding("warning", "payment_request", "Mentions a payment or fee",
                                "Genuine circulars rarely ask for payment to a personal UPI ID, phone number or "
                                "account. Confirm any fee on the official website.",
                                {"page": _page_of(pages, m.start()), "snippet": _line_at(full, m.start())}))
    else:
        findings.append(Finding("passed", "payment_request", "No payment request found",
                                "The extracted text does not ask for money."))
    phones = PHONE.findall(full)
    if phones and claims_official:
        findings.append(Finding("warning", "mobile_contact", "Uses a personal mobile number as contact",
                                "Official notices usually list landline or toll-free helplines. Verify the number on "
                                "the official website before calling.", {"snippet": phones[0]}))

    # 5. Reference numbers - no authoritative public registry is integrated
    for m in list(REF_NO.finditer(full))[:2]:
        findings.append(Finding("could_not_check", "reference_number", f"Reference number {m.group(2)}",
                                "SatyaSetu has no access to an authoritative register of reference numbers, so this "
                                "number was not checked. A number that cannot be found is not proof of forgery.",
                                {"page": _page_of(pages, m.start()), "snippet": _line_at(full, m.start())}))

    # 6. File metadata
    meta = metadata or {}
    if meta:
        producer = " ".join(str(meta.get(k, "")) for k in ("producer", "creator")).lower()
        editor = next((e for e in EDITORS if e in producer), None)
        if editor and claims_official:
            findings.append(Finding("warning", "editing_software",
                                    f"Created with consumer editing software ({editor.title()})",
                                    "Official circulars are rarely produced with design/photo editors. This is a "
                                    "warning sign only; legitimate offices sometimes use such tools."))
        cd, md = meta.get("creation_date"), meta.get("mod_date")
        if cd and md and str(md)[:10] > str(cd)[:10]:
            findings.append(Finding("warning", "modified_after_creation", "File was modified after creation",
                                    f"Created {str(cd)[:10]}, last modified {str(md)[:10]}. Many genuine files are "
                                    "edited; treat this as context only."))
        if issue and issue.value and cd:
            try:
                created = date.fromisoformat(str(cd)[:10])
                if created < issue.value.replace(year=issue.value.year - 1):
                    findings.append(Finding("warning", "created_before_issue",
                                            "File created long before its stated issue date",
                                            f"File created {created}, but the document is dated {issue.raw}."))
            except ValueError:
                pass
    else:
        findings.append(Finding("could_not_check", "metadata", "No file metadata",
                                "Images and scans carry little reliable metadata; this check was not possible."))

    # 7. Comparison with official publications happens via the claim-verification pipeline.
    if (extraction or {}).get("method") == "ocr":
        conf = (extraction or {}).get("confidence")
        if conf is not None and conf < 70:
            findings.append(Finding("could_not_check", "ocr_quality", "Low text-recognition confidence",
                                    f"OCR confidence was {conf:.0f}/100; some text may be misread, so date and "
                                    "contact checks may be incomplete."))
    order = {"confirmed_inconsistency": 0, "warning": 1, "could_not_check": 2, "passed": 3}
    findings.sort(key=lambda f: order[f.category])
    return [asdict(f) for f in findings]


def _page_of(pages: list[str], pos: int) -> int:
    acc = 0
    for i, p in enumerate(pages, 1):
        acc += len(p) + 1
        if pos < acc:
            return i
    return len(pages)
