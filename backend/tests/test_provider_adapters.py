"""Provider adapters tested against mocked HTTP (respx). These verify request
shape and error handling; they are NOT live-provider validation."""
import httpx
import pytest
import respx
from pydantic import BaseModel, SecretStr

from app.pipeline.llm_io import ClaimExtraction
from app.providers.errors import ContentBlocked, InvalidModelOutput, ProviderNotConfigured, QuotaExhausted
from app.providers.llm import CallStats, GeminiProvider, to_gemini_schema
from app.providers.search import TavilySearch

GEM = "https://generativelanguage.googleapis.com/v1beta/models"


class Out(BaseModel):
    answer: str
    n: int | None = None


def gemini_ok(text: str, tokens: int = 42):
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}],
                                     "usageMetadata": {"totalTokenCount": tokens}})


@pytest.fixture
def keyed(settings):
    settings.gemini_api_key = SecretStr("test-key")
    settings.tavily_api_key = SecretStr("tvly-test")
    settings.gemini_model, settings.gemini_fallback_model = "model-a", "model-b"
    return settings


def test_schema_conversion_handles_optional_enum_nested():
    s = to_gemini_schema(ClaimExtraction)
    claim = s["properties"]["claims"]["items"]
    assert claim["properties"]["claim_type"]["enum"][0] == "factual"
    assert claim["properties"]["attribution"]["nullable"] is True
    assert s["type"] == "OBJECT" and "$ref" not in str(s)


def test_not_configured(settings):
    settings.gemini_api_key = None
    with pytest.raises(ProviderNotConfigured):
        GeminiProvider(settings)


@respx.mock
async def test_gemini_success_and_key_in_header(keyed):
    route = respx.post(f"{GEM}/model-a:generateContent").mock(return_value=gemini_ok('{"answer": "ok"}'))
    stats = CallStats()
    out = await GeminiProvider(keyed).generate_json(system="s", prompt="p", out=Out, stats=stats)
    assert out.answer == "ok" and stats.tokens == 42 and stats.models == ["model-a"]
    req = route.calls[0].request
    assert req.headers["x-goog-api-key"] == "test-key" and "key=" not in str(req.url)
    body = req.read().decode()
    assert '"responseMimeType":"application/json"' in body.replace(" ", "")


@respx.mock
async def test_gemini_invalid_json_retried_once_then_fails(keyed):
    respx.post(f"{GEM}/model-a:generateContent").mock(return_value=gemini_ok("not json"))
    with pytest.raises(InvalidModelOutput):
        await GeminiProvider(keyed).generate_json(system="s", prompt="p", out=Out, stats=CallStats())


@respx.mock
async def test_gemini_daily_quota_falls_back_to_second_model(keyed):
    quota = httpx.Response(429, json={"error": {"message": "quota", "details": [
        {"@type": "type.googleapis.com/google.rpc.QuotaFailure",
         "violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}]}})
    respx.post(f"{GEM}/model-a:generateContent").mock(return_value=quota)
    respx.post(f"{GEM}/model-b:generateContent").mock(return_value=gemini_ok('{"answer": "fallback"}'))
    stats = CallStats()
    out = await GeminiProvider(keyed).generate_json(system="s", prompt="p", out=Out, stats=stats)
    assert out.answer == "fallback" and stats.models == ["model-b"]


@respx.mock
async def test_gemini_all_models_exhausted(keyed):
    quota = httpx.Response(429, json={"error": {"message": "quota", "details": [
        {"@type": "x.QuotaFailure", "violations": [{"quotaId": "PerDay"}]}]}})
    respx.post(url__regex=rf"{GEM}/.*").mock(return_value=quota)
    with pytest.raises(QuotaExhausted):
        await GeminiProvider(keyed).generate_json(system="s", prompt="p", out=Out, stats=CallStats())


@respx.mock
async def test_gemini_blocked_prompt(keyed):
    respx.post(f"{GEM}/model-a:generateContent").mock(
        return_value=httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}}))
    with pytest.raises(ContentBlocked):
        await GeminiProvider(keyed).generate_json(system="s", prompt="p", out=Out, stats=CallStats())


async def test_local_daily_budget_blocks_before_request(keyed):
    keyed.gemini_max_requests_per_day = 0
    with respx.mock(assert_all_called=False) as m:
        route = m.post(url__regex=r".*generativelanguage.*")
        with pytest.raises(QuotaExhausted):
            await GeminiProvider(keyed).generate_json(system="s", prompt="p", out=Out, stats=CallStats())
        assert not route.called


@respx.mock
async def test_tavily_maps_results_and_uses_basic_depth(keyed):
    route = respx.post("https://api.tavily.com/search").mock(return_value=httpx.Response(200, json={
        "query": "q", "results": [{"url": "https://pib.gov.in/x", "title": "T", "content": "snippet", "score": 0.9,
                                   "raw_content": "full text"}], "response_time": 0.5}))
    hits = await TavilySearch(keyed).search("q", country="india", stats=CallStats())
    assert hits[0].url == "https://pib.gov.in/x" and hits[0].raw_content == "full text"
    import json
    body = json.loads(route.calls[0].request.read())
    assert body["search_depth"] == "basic" and body["include_answer"] is False and body["country"] == "india"
    assert route.calls[0].request.headers["authorization"] == "Bearer tvly-test"


@respx.mock
async def test_tavily_credit_exhausted(keyed):
    respx.post("https://api.tavily.com/search").mock(return_value=httpx.Response(432, json={"detail": "limit"}))
    with pytest.raises(QuotaExhausted):
        await TavilySearch(keyed).search("q", country=None, stats=CallStats())
