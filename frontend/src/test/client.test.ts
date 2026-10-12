import { afterEach, describe, expect, it, vi } from "vitest";
import { api, resetSessionGate } from "../api/client";

afterEach(() => {
  vi.unstubAllGlobals();
  resetSessionGate();
});

describe("session gate", () => {
  it("sends no other request until the first one (which creates the session) has returned", async () => {
    const order: string[] = [];
    let releaseFirst!: () => void;
    const firstDone = new Promise<void>((r) => (releaseFirst = r));
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      order.push(`start ${url}`);
      if (url === "/api/preferences") await firstDone;
      order.push(`end ${url}`);
      return new Response(JSON.stringify([]), { status: 200, headers: { "content-type": "application/json" } });
    }));
    const a = api.getPreferences();
    const b = api.capabilities();
    const c = api.listConversations();
    await new Promise((r) => setTimeout(r, 10));
    expect(order).toEqual(["start /api/preferences"]); // b and c are held back
    releaseFirst();
    await Promise.all([a, b, c]);
    expect(order[1]).toBe("end /api/preferences");
    expect(order).toContain("start /api/capabilities");
  });

  it("a failed first request does not block later requests", async () => {
    const { _setSleepForTests } = await import("../api/client");
    _setSleepForTests(() => Promise.resolve());
    let n = 0;
    vi.stubGlobal("fetch", vi.fn(async () => {
      n += 1;
      if (n === 1) return new Response(JSON.stringify({ code: "internal", message: "boom" }), { status: 500, headers: { "content-type": "application/json" } });
      return new Response("{}", { status: 200, headers: { "content-type": "application/json" } });
    }));
    await expect(api.capabilities()).rejects.toThrow("boom"); // app errors are not retried
    await expect(api.capabilities()).resolves.toEqual({});
  });

  it("a transient network failure on a GET is retried", async () => {
    const { _setSleepForTests } = await import("../api/client");
    _setSleepForTests(() => Promise.resolve());
    let n = 0;
    vi.stubGlobal("fetch", vi.fn(async () => {
      n += 1;
      if (n === 1) throw new TypeError("network down");
      return new Response("{}", { status: 200, headers: { "content-type": "application/json" } });
    }));
    await expect(api.capabilities()).resolves.toEqual({});
    expect(n).toBe(2);
  });
});

describe("cold-start resilience", () => {
  const html = (status: number) => new Response("<html>Service waking up</html>", { status, headers: { "content-type": "text/html" } });
  const ok = (data: unknown) => new Response(JSON.stringify(data), { status: 200, headers: { "content-type": "application/json" } });

  it("retries a GET through hosting-layer HTML responses and reports waking -> ok", async () => {
    const { _setSleepForTests, onConnectionState } = await import("../api/client");
    _setSleepForTests(() => Promise.resolve());
    const states: string[] = [];
    const off = onConnectionState((s) => states.push(s));
    const responses = [html(503), html(200), ok({ live_verification: true })];
    const fetchMock = vi.fn(async () => responses.shift()!);
    vi.stubGlobal("fetch", fetchMock);
    await expect(api.capabilities()).resolves.toEqual({ live_verification: true });
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(states).toEqual(["waking", "ok"]);
    off();
  });

  it("never returns HTML as data", async () => {
    const { _setSleepForTests, RETRY_DELAYS_MS } = await import("../api/client");
    _setSleepForTests(() => Promise.resolve());
    vi.stubGlobal("fetch", vi.fn(async () => html(200)));
    await expect(api.capabilities()).rejects.toThrow("did not come online");
    expect((fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.length).toBe(RETRY_DELAYS_MS.length + 1);
  });

  it("does not resend a POST after a network error (it may already have been processed)", async () => {
    const { _setSleepForTests } = await import("../api/client");
    _setSleepForTests(() => Promise.resolve());
    api.listConversations().catch(() => {}); // establish the session gate first
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("connection reset"); }));
    await expect(api.sendMessage("c1", "hello")).rejects.toThrow("internet connection");
    expect((fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.length).toBeLessThanOrEqual(13); // the GET may retry; the POST is sent once
    const posts = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.filter((c) => (c[1] as RequestInit)?.method === "POST");
    expect(posts.length).toBe(1);
  });

  it("resends a POST when the hosting layer answered (request never reached the app)", async () => {
    const { _setSleepForTests } = await import("../api/client");
    _setSleepForTests(() => Promise.resolve());
    const responses = [ok([]), html(502), ok({ id: "m1" })];
    vi.stubGlobal("fetch", vi.fn(async () => responses.shift()!));
    await api.listConversations();
    await expect(api.sendMessage("c1", "hello")).resolves.toEqual({ id: "m1" });
  });
});


describe("slow first response (sleeping host holds the connection)", () => {
  it("shows waking while a request is pending past SLOW_MS, then ok", async () => {
    vi.useFakeTimers();
    const { onConnectionState, SLOW_MS } = await import("../api/client");
    const states: string[] = [];
    const off = onConnectionState((s) => states.push(s));
    let release!: (r: Response) => void;
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>((r) => (release = r))));
    const p = api.capabilities();
    await vi.advanceTimersByTimeAsync(SLOW_MS + 10);
    expect(states).toEqual(["waking"]);
    release(new Response("{}", { status: 200, headers: { "content-type": "application/json" } }));
    await p;
    expect(states).toEqual(["waking", "ok"]);
    off();
    vi.useRealTimers();
  });
});
