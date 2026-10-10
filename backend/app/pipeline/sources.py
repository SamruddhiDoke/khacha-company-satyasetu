"""Transparent source classification and ranking.

Tiers describe what kind of publisher a domain is, not whether it is right.
An official source is authoritative about its own announcements; for other
questions it is weighed like any other credible source. The weights are used
by the verdict rules in `verdicts.py`."""
from __future__ import annotations

from urllib.parse import urlsplit

TIER_WEIGHT = {"official": 3, "fact_check": 3, "news": 2, "reference": 2, "other": 1}

OFFICIAL_SUFFIXES = (
    ".gov.in", ".nic.in", ".gov", ".gov.uk", ".gov.au", ".gc.ca", ".europa.eu", ".mil", ".res.in", ".int",
)
# Academic domains (.ac.in, .edu) are NOT official by suffix: they host lecture notes, student pages and
# course PDFs. They count as "other" unless an institution is explicitly listed (e.g. nta.ac.in).
OFFICIAL_DOMAINS = {
    "who.int", "un.org", "unicef.org", "worldbank.org", "imf.org", "rbi.org.in", "sebi.gov.in", "eci.gov.in",
    "pib.gov.in", "india.gov.in", "mygov.in", "uidai.gov.in", "npci.org.in", "icmr.gov.in", "mohfw.gov.in",
    "incometax.gov.in", "epfindia.gov.in", "isro.gov.in", "nta.ac.in", "cbse.gov.in", "ugc.gov.in",
    "aicte-india.org", "irctc.co.in", "indianrailways.gov.in", "fssai.gov.in", "cdsco.gov.in", "nhai.gov.in",
    "lic.in", "sbi.co.in", "who.int", "cdc.gov", "nih.gov", "fda.gov", "ema.europa.eu", "nhs.uk",
}
FACT_CHECK_DOMAINS = {
    "altnews.in", "boomlive.in", "factly.in", "factchecker.in", "vishvasnews.com", "newschecker.in",
    "newsmeter.in", "thelogicalindian.com", "factcheck.afp.com", "fullfact.org", "snopes.com", "politifact.com",
    "factcheck.org", "leadstories.com", "healthfeedback.org", "sciencefeedback.co", "indiatoday.in/fact-check",
    "thequint.com/news/webqoof", "reuters.com/fact-check", "apnews.com/hub/ap-fact-check",
}
NEWS_DOMAINS = {
    "thehindu.com", "indianexpress.com", "hindustantimes.com", "ndtv.com", "indiatoday.in", "livemint.com",
    "economictimes.indiatimes.com", "timesofindia.indiatimes.com", "business-standard.com", "theprint.in",
    "scroll.in", "thewire.in", "deccanherald.com", "news18.com", "moneycontrol.com", "financialexpress.com",
    "thequint.com", "newindianexpress.com", "telegraphindia.com", "tribuneindia.com", "loksatta.com",
    "lokmat.com", "maharashtratimes.com", "bhaskar.com", "jagran.com", "amarujala.com", "aajtak.in",
    "abplive.com", "zeenews.india.com", "reuters.com", "apnews.com", "bbc.com", "bbc.co.uk", "theguardian.com",
    "nytimes.com", "washingtonpost.com", "aljazeera.com", "cnn.com", "npr.org", "bloomberg.com", "ft.com",
    "economist.com", "wsj.com", "pti.in", "ptinews.com", "ani.in", "aninews.in", "dw.com", "france24.com",
}
REFERENCE_DOMAINS = {
    "wikipedia.org", "britannica.com", "nature.com", "science.org", "thelancet.com", "nejm.org", "bmj.com",
    "jamanetwork.com", "pubmed.ncbi.nlm.nih.gov", "cochrane.org", "mayoclinic.org", "clevelandclinic.org",
    "worldometers.info", "statista.com", "ourworldindata.org", "arxiv.org", "prsindia.org",
}


def domain_of(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _matches(host: str, path: str, entries: set[str]) -> bool:
    for e in entries:
        if "/" in e:
            d, p = e.split("/", 1)
            if (host == d or host.endswith("." + d)) and path.lstrip("/").startswith(p):
                return True
        elif host == e or host.endswith("." + e):
            return True
    return False


def classify(url: str) -> str:
    host = domain_of(url)
    path = urlsplit(url).path
    if _matches(host, path, FACT_CHECK_DOMAINS) or "/fact-check" in path or "/factcheck" in path:
        return "fact_check"
    if host in OFFICIAL_DOMAINS or host.endswith(OFFICIAL_SUFFIXES) or _matches(host, path, OFFICIAL_DOMAINS):
        return "official"
    if _matches(host, path, NEWS_DOMAINS):
        return "news"
    if _matches(host, path, REFERENCE_DOMAINS):
        return "reference"
    return "other"


def rank_key(tier: str, score: float | None) -> float:
    return TIER_WEIGHT[tier] + (score or 0.0)


def registrable_domain(host: str) -> str:
    """Best-effort eTLD+1 for common suffixes (used for de-duplication and lookalike checks)."""
    parts = host.lower().strip(".").split(".")
    two_level = {"gov.in", "nic.in", "co.in", "org.in", "ac.in", "net.in", "res.in", "edu.in", "co.uk", "gov.uk",
                 "ac.uk", "org.uk", "com.au", "gov.au", "co.jp"}
    if len(parts) >= 3 and ".".join(parts[-2:]) in two_level:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])
