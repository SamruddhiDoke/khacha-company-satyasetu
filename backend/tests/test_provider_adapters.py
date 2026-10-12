"""Provider adapters tested against mocked HTTP (respx). These verify request
shape and error handling; they are NOT live-provider validation."""
import httpx
import pytest
import respx
from pydantic import BaseModel, SecretStr

from app.pipeline.llm_io import ClaimExtraction
from app.providers.errors import ContentBlocked, InvalidModelOutput, ProviderError, ProviderNotConfigured, QuotaExhausted
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


@respx.mock
async def test_gemini3_gets_low_thinking_level(keyed):
    keyed.gemini_model = "gemini-3.8-flash"
    route = respx.post(f"{GEM}/gemini-3.8-flash:generateContent").mock(return_value=gemini_ok('{"answer": "ok"}'))
    await GeminiProvider(keyed).generate_json(system="s", prompt="p", out=Out, stats=CallStats())
    import json
    body = json.loads(route.calls[0].request.read())
    assert body["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "low"}


@respx.mock
async def test_gemini_timeout_falls_back_without_retrying_same_model(keyed):
    a = respx.post(f"{GEM}/model-a:generateContent").mock(side_effect=httpx.ReadTimeout("slow"))
    respx.post(f"{GEM}/model-b:generateContent").mock(return_value=gemini_ok('{"answer": "fallback"}'))
    stats = CallStats()
    out = await GeminiProvider(keyed).generate_json(system="s", prompt="p", out=Out, stats=stats)
    assert out.answer == "fallback" and a.call_count == 1 and stats.models == ["model-b"]


DAILY_429 = httpx.Response(429, json={"error": {"message": "quota", "details": [
    {"@type": "type.googleapis.com/google.rpc.QuotaFailure",
     "violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}]}})


@respx.mock
async def test_exhausted_model_is_skipped_until_reset_and_slot_released(keyed):
    a = respx.post(f"{GEM}/model-a:generateContent").mock(return_value=DAILY_429)
    b = respx.post(f"{GEM}/model-b:generateContent").mock(return_value=gemini_ok('{"answer": "fb"}'))
    p = GeminiProvider(keyed)
    for _ in range(3):
        assert (await p.generate_json(system="s", prompt="p", out=Out, stats=CallStats())).answer == "fb"
    assert a.call_count == 1 and b.call_count == 3          # primary tried once, then skipped
    assert len(p._limiter._times) == 3                        # the refused request's slot was given back
    assert p.available_models() == ["model-b"]


@respx.mock
async def test_exhausted_model_returns_after_pacific_midnight(keyed):
    from datetime import datetime, timezone
    respx.post(f"{GEM}/model-a:generateContent").mock(return_value=DAILY_429)
    respx.post(f"{GEM}/model-b:generateContent").mock(return_value=gemini_ok('{"answer": "fb"}'))
    p = GeminiProvider(keyed)
    await p.generate_json(system="s", prompt="p", out=Out, stats=CallStats())
    reset = p._exhausted_until["model-a"]
    # 15:23 UTC on 10 Oct 2026 (08:23 PDT) -> next reset is 00:00 PDT 11 Oct = 07:00 UTC
    assert p.next_quota_reset(datetime(2026, 10, 10, 15, 23, tzinfo=timezone.utc)) == \
        datetime(2026, 10, 11, 7, 0, tzinfo=timezone.utc)
    assert p.available_models(now=reset) == ["model-a", "model-b"]


@respx.mock
async def test_all_models_exhausted_raises_without_http_call(keyed):
    respx.post(url__regex=rf"{GEM}/.*").mock(return_value=DAILY_429)
    p = GeminiProvider(keyed)
    with pytest.raises(QuotaExhausted):
        await p.generate_json(system="s", prompt="p", out=Out, stats=CallStats())
    calls = len(respx.calls)
    with pytest.raises(QuotaExhausted, match="until"):
        await p.generate_json(system="s", prompt="p", out=Out, stats=CallStats())
    assert len(respx.calls) == calls  # nothing sent once every model is known to be exhausted


async def test_local_budget_does_not_mark_model_exhausted(keyed):
    keyed.gemini_max_requests_per_day = 0
    p = GeminiProvider(keyed)
    with pytest.raises(QuotaExhausted):
        await p.generate_json(system="s", prompt="p", out=Out, stats=CallStats())
    assert p._exhausted_until == {}


@respx.mock
async def test_overloaded_model_falls_back_after_one_retry(keyed):
    overloaded = httpx.Response(503, json={"error": {"message": "This model is currently experiencing high demand."}})
    a = respx.post(f"{GEM}/model-a:generateContent").mock(return_value=overloaded)
    respx.post(f"{GEM}/model-b:generateContent").mock(return_value=gemini_ok('{"answer": "fb"}'))
    stats = CallStats()
    out = await GeminiProvider(keyed).generate_json(system="s", prompt="p", out=Out, stats=stats)
    assert out.answer == "fb" and a.call_count == 2 and stats.models == ["model-b"]


@respx.mock
async def test_all_models_overloaded_fails_honestly(keyed):
    respx.post(url__regex=rf"{GEM}/.*").mock(return_value=httpx.Response(503, json={"error": {"message": "high demand"}}))
    with pytest.raises(ProviderError, match="503"):
        await GeminiProvider(keyed).generate_json(system="s", prompt="p", out=Out, stats=CallStats())
