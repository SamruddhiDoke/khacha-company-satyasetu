"""SSRF-safe HTTP fetching for user-supplied and search-result URLs.

Protections:
- http/https only, default ports only, no embedded credentials;
- every resolved address must be globally routable (blocks localhost, RFC1918,
  link-local / cloud metadata 169.254.169.254, CGNAT, multicast, reserved, IPv6 ULA...);
- the TCP connection is made to the vetted IP (TLS still verifies the real hostname),
  so DNS rebinding between check and connect is not possible;
- redirects are followed manually and every hop is re-validated;
- response size, content type and total time are bounded.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

def user_agent() -> str:
    # Some sites (e.g. Wikipedia) reject automated clients without contact details. FETCH_CONTACT is
    # optional and empty by default so no personal information is sent unless the user opts in.
    from app.config import get_settings
    contact = get_settings().fetch_contact.strip()
    return f"SatyaSetu/0.1 (local fact-checking assistant{'; ' + contact if contact else ''})"
ALLOWED_TYPES = ("text/html", "application/xhtml+xml", "text/plain", "application/pdf")
BLOCKED_HOSTNAMES = {"localhost", "metadata.google.internal", "metadata", "instance-data"}


class UnsafeURL(Exception):
    pass


class FetchFailed(Exception):
    pass


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int
    content_type: str
    body: bytes


def _check_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if not ip.is_global or ip.is_multicast or ip.is_reserved or ip.is_loopback or ip.is_link_local or ip.is_private:
        raise UnsafeURL(f"destination address {ip} is not a public internet address")


def validate_url_syntax(url: str) -> tuple[str, str, int]:
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https"):
        raise UnsafeURL("only http and https URLs are allowed")
    if parts.username or parts.password:
        raise UnsafeURL("URLs with embedded credentials are not allowed")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise UnsafeURL("URL has no host")
    if host in BLOCKED_HOSTNAMES or host.endswith((".localhost", ".local", ".internal", ".lan")):
        raise UnsafeURL(f"host {host} is not allowed")
    default_port = 443 if parts.scheme == "https" else 80
    port = parts.port or default_port
    if port != default_port:
        raise UnsafeURL("non-standard ports are not allowed")
    try:  # literal IP address in the URL
        _check_ip(ipaddress.ip_address(host))
    except ValueError:
        pass
    return parts.scheme, host, port


async def resolve_public(host: str, port: int) -> str:
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass
    loop = asyncio.get_running_loop()
    try:
        infos = await asyncio.wait_for(loop.getaddrinfo(host, port, type=socket.SOCK_STREAM), timeout=5)
    except (socket.gaierror, asyncio.TimeoutError) as e:
        raise FetchFailed(f"could not resolve {host}") from e
    addrs = {info[4][0] for info in infos}
    if not addrs:
        raise FetchFailed(f"could not resolve {host}")
    for a in addrs:
        _check_ip(ipaddress.ip_address(a.split("%")[0]))
    # prefer IPv4 for wider reachability inside Docker
    return sorted(addrs, key=lambda a: ":" in a)[0]


async def safe_fetch(
    url: str,
    *,
    timeout_s: float = 10.0,
    max_bytes: int = 3_000_000,
    max_redirects: int = 5,
    client: httpx.AsyncClient | None = None,
) -> FetchResult:
    own_client = client is None
    client = client or httpx.AsyncClient(follow_redirects=False, timeout=httpx.Timeout(timeout_s, connect=5))
    try:
        return await asyncio.wait_for(_fetch(client, url, max_bytes, max_redirects), timeout=timeout_s + 2)
    except asyncio.TimeoutError as e:
        raise FetchFailed("timed out") from e
    finally:
        if own_client:
            await client.aclose()


async def _fetch(client: httpx.AsyncClient, url: str, max_bytes: int, max_redirects: int) -> FetchResult:
    current = url
    for _ in range(max_redirects + 1):
        scheme, host, port = validate_url_syntax(current)
        ip = await resolve_public(host, port)
        parts = urlsplit(current)
        ip_netloc = f"[{ip}]" if ":" in ip else ip
        pinned = urlunsplit((scheme, ip_netloc, parts.path or "/", parts.query, ""))
        headers = {"Host": parts.netloc.split("@")[-1], "User-Agent": user_agent(),
                   "Accept": "text/html,application/xhtml+xml,text/plain,application/pdf;q=0.9,*/*;q=0.1",
                   "Accept-Language": "en-IN,en;q=0.9,hi;q=0.6"}
        req = client.build_request("GET", pinned, headers=headers,
                                   extensions={"sni_hostname": host} if scheme == "https" else {})
        try:
            resp = await client.send(req, stream=True)
        except httpx.HTTPError as e:
            raise FetchFailed(f"connection failed: {type(e).__name__}") from e
        try:
            if resp.status_code in (301, 302, 303, 307, 308):
                loc = resp.headers.get("location")
                if not loc:
                    raise FetchFailed("redirect without location")
                current = urljoin(current, loc)
                continue
            if resp.status_code >= 400:
                raise FetchFailed(f"HTTP {resp.status_code}")
            ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
            if ctype and not ctype.startswith(ALLOWED_TYPES):
                raise FetchFailed(f"unsupported content type {ctype}")
            declared = resp.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > max_bytes:
                raise FetchFailed("response too large")
            chunks, total = [], 0
            async for chunk in resp.aiter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    raise FetchFailed("response too large")
                chunks.append(chunk)
            return FetchResult(url=url, final_url=current, status=resp.status_code,
                               content_type=ctype or "text/html", body=b"".join(chunks))
        finally:
            await resp.aclose()
    raise FetchFailed("too many redirects")
