from app.core.safe_fetch import FetchResult
from app.pipeline.retrieval import extract_page
from app.pipeline.sources import classify, registrable_domain
from app.pipeline.text import extract_urls, quote_in_text, select_passages

SOURCE = "The Reserve Bank of India said on Monday that “no such directive” was issued.\nAccounts remain active."


def test_quote_verbatim_with_typographic_quotes_and_case():
    assert quote_in_text('the reserve bank of india said on Monday that "no such directive" was issued', SOURCE)


def test_quote_paraphrase_rejected():
    assert not quote_in_text("RBI denied issuing any directive on Monday", SOURCE)


def test_quote_too_short_rejected():
    assert not quote_in_text("Accounts", SOURCE)


def test_extract_urls_strips_punctuation():
    assert extract_urls("see https://example.com/a?b=1. now") == ["https://example.com/a?b=1"]


def test_select_passages_prefers_relevant_and_numbers():
    text = ("Weather today is sunny and warm across the region with light winds.\n\n"
            "The scholarship provides Rs 50000 to students from families earning under 8 lakh per year.\n\n"
            "Sports news: the local team won the match in a close finish on Sunday evening.")
    top = select_passages(text, ["scholarship", "50000", "students"], k=1)
    assert top and "scholarship" in top[0].text


def test_classify_tiers():
    assert classify("https://www.rbi.org.in/x") == "official"
    assert classify("https://pib.gov.in/PressRelease") == "official"
    assert classify("https://www.boomlive.in/fact-check/x") == "fact_check"
    assert classify("https://www.reuters.com/fact-check/abc") == "fact_check"
    assert classify("https://www.thehindu.com/news") == "news"
    assert classify("https://en.wikipedia.org/wiki/X") == "reference"
    assert classify("https://random-blog.xyz/post") == "other"
    assert classify("https://sbi.co.in.fake-kyc.com/") == "other"  # lookalike is not official


def test_registrable_domain():
    assert registrable_domain("www.mohfw.gov.in") == "mohfw.gov.in"
    assert registrable_domain("a.b.example.com") == "example.com"


def test_extract_page_html():
    html = ("<html><head><title>Official clarification</title></head><body><nav>menu</nav><article>"
            + "".join(f"<p>Paragraph {i}: The ministry clarified that the scheme deadline was not extended "
                      f"and applications close on 31 March as announced earlier.</p>" for i in range(5))
            + "</article><footer>footer</footer></body></html>")
    page = extract_page(FetchResult("https://x.gov.in", "https://x.gov.in", 200, "text/html", html.encode()))
    assert "deadline was not extended" in page.text
    assert "menu" not in page.text


def test_academic_domains_are_not_official_by_suffix():
    assert classify("https://www.lkouniv.ac.in/site/writereaddata/siteContent/notes.pdf") == "other"
    assert classify("https://www.jnpg.ac.in/Upload/EContent/RBI.pdf") == "other"
    assert classify("https://ocw.mit.edu/courses/x") == "other"
    assert classify("https://nta.ac.in/notice") == "official"  # explicitly listed institution
    assert classify("https://www.mohfw.gov.in/") == "official"


def test_hosted_database_urls_are_normalized_for_asyncpg():
    from app.config import Settings
    s = Settings(database_url="postgresql://u:p@ep-x.ap-southeast-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require")
    assert s.database_url == "postgresql+asyncpg://u:p@ep-x.ap-southeast-1.aws.neon.tech/neondb?ssl=require"
    assert Settings(database_url="postgres://u:p@h:5432/db").database_url == "postgresql+asyncpg://u:p@h:5432/db"
    local = "postgresql+asyncpg://satyasetu:x@db:5432/satyasetu"
    assert Settings(database_url=local).database_url == local
