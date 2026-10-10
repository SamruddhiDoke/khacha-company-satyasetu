import httpx
import pytest

from app.core import safe_fetch as sf
from app.core.safe_fetch import FetchFailed, UnsafeURL, safe_fetch, validate_url_syntax


@pytest.mark.parametrize("url", [
    "http://localhost/admin", "http://127.0.0.1/", "http://10.0.0.5/", "http://192.168.1.1/", "http://172.16.0.1/",
    "http://169.254.169.254/latest/meta-data/", "http://[::1]/", "http://[fd00::1]/", "http://100.64.0.1/",
    "http://0.0.0.0/", "file:///etc/passwd", "ftp://example.com/", "gopher://example.com/",
    "http://example.com:8080/", "http://user:pass@example.com/", "http://metadata.google.internal/",
    "http://printer.local/", "http://[::ffff:127.0.0.1]/",
])
def test_blocked_urls(url):
    with pytest.raises(UnsafeURL):
        validate_url_syntax(url)


def test_public_url_allowed():
    assert validate_url_syntax("https://www.rbi.org.in/a?b=1")[1] == "www.rbi.org.in"


async def test_hostname_resolving_to_private_ip_is_blocked(monkeypatch):
    async def fake_getaddrinfo(host, port, type=0):
        return [(2, 1, 6, "", ("10.1.2.3", port))]

    import asyncio
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(UnsafeURL):
        await sf.resolve_public("rebind.example.com", 80)


async def test_redirect_to_metadata_endpoint_is_blocked(monkeypatch):
    async def fake_resolve(host, port):
        return "93.184.216.34"

    monkeypatch.setattr(sf, "resolve_public", fake_resolve)

    def handler(request: httpx.Request):
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
    with pytest.raises(UnsafeURL):
        await safe_fetch("https://public.example.com/start", client=client)


async def test_size_limit_and_content_type(monkeypatch):
    async def fake_resolve(host, port):
        return "93.184.216.34"

    monkeypatch.setattr(sf, "resolve_public", fake_resolve)

    def big(request):
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"x" * 5000)

    client = httpx.AsyncClient(transport=httpx.MockTransport(big))
    with pytest.raises(FetchFailed, match="too large"):
        await safe_fetch("https://public.example.com/", client=client, max_bytes=1000)

    def binary(request):
        return httpx.Response(200, headers={"content-type": "application/octet-stream"}, content=b"\x00")

    client = httpx.AsyncClient(transport=httpx.MockTransport(binary))
    with pytest.raises(FetchFailed, match="unsupported content type"):
        await safe_fetch("https://public.example.com/", client=client)


async def test_connection_pinned_to_vetted_ip(monkeypatch):
    async def fake_resolve(host, port):
        return "93.184.216.34"

    monkeypatch.setattr(sf, "resolve_public", fake_resolve)
    seen = {}

    def handler(request: httpx.Request):
        seen["host"] = request.url.host
        seen["header"] = request.headers["host"]
        seen["sni"] = request.extensions.get("sni_hostname")
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"ok")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    res = await safe_fetch("https://news.example.com/a", client=client)
    assert res.body == b"ok"
    assert seen == {"host": "93.184.216.34", "header": "news.example.com", "sni": "news.example.com"}
