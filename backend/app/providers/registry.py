"""Builds provider instances from configuration. There is deliberately no
"demo" or "offline" provider: if a provider is not configured, verification
reports `provider_not_configured` instead of producing results."""
from __future__ import annotations

from app.config import get_settings
from app.providers.errors import ProviderNotConfigured
from app.providers.llm import GeminiProvider, LLMProvider
from app.providers.search import GoogleFactCheckSearch, SearchProvider, TavilySearch

_llm: LLMProvider | None = None
_search: SearchProvider | None = None
_factcheck: SearchProvider | None = None
_factcheck_checked = False


def get_llm() -> LLMProvider:
    global _llm
    if _llm is None:
        _llm = GeminiProvider(get_settings())
    return _llm


def get_search() -> SearchProvider:
    global _search
    if _search is None:
        _search = TavilySearch(get_settings())
    return _search


def get_factcheck() -> SearchProvider | None:
    global _factcheck, _factcheck_checked
    if not _factcheck_checked:
        _factcheck_checked = True
        try:
            _factcheck = GoogleFactCheckSearch(get_settings())
        except ProviderNotConfigured:
            _factcheck = None
    return _factcheck


def override(*, llm: LLMProvider | None = None, search: SearchProvider | None = None,
             factcheck: SearchProvider | None = None) -> None:
    """Test hook only: lets automated tests inject mock providers explicitly."""
    global _llm, _search, _factcheck, _factcheck_checked
    _llm, _search, _factcheck, _factcheck_checked = llm, search, factcheck, True


def reset() -> None:
    global _llm, _search, _factcheck, _factcheck_checked
    _llm = _search = _factcheck = None
    _factcheck_checked = False
