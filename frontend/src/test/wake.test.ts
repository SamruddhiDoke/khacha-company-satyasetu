import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.resetModules();
});

const html502 = () => new Response("<html>502</html>", { status: 502, headers: { "content-type": "text/html" } });
const ok = () => new Response("{}", { status: 200, headers: { "content-type": "application/json" } });

describe("waking a sleeping backend", () => {
  it("sends one direct no-cors request to VITE_WAKE_URL when the proxy reports the server unavailable", async () => {
    vi.stubEnv("VITE_WAKE_URL", "https://backend.example/api/health");
    vi.resetModules();
    const client = await import("../api/client");
    client._setSleepForTests(() => Promise.resolve());
    const responses = [html502(), html502(), ok()];
    const fetchMock = vi.fn(async (url: string, _init?: RequestInit) => (url.startsWith("https://backend.example") ? ok() : responses.shift()!));
    vi.stubGlobal("fetch", fetchMock);
    await client.api.capabilities();
    const wakes = fetchMock.mock.calls.filter((c) => String(c[0]).startsWith("https://backend.example"));
    expect(wakes.length).toBe(1); // at most once per minute, even though two 502s were seen
    expect(wakes[0][1]).toMatchObject({ mode: "no-cors", credentials: "omit" });
  });

  it("never pings anything when VITE_WAKE_URL is not configured (local builds)", async () => {
    vi.resetModules();
    const client = await import("../api/client");
    expect(client.wakeBackend()).toBe(false);
  });
});
