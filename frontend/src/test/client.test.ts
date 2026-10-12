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
    let n = 0;
    vi.stubGlobal("fetch", vi.fn(async () => {
      n += 1;
      if (n === 1) throw new TypeError("network down");
      return new Response("{}", { status: 200, headers: { "content-type": "application/json" } });
    }));
    await expect(api.capabilities()).rejects.toThrow("Cannot reach");
    await expect(api.capabilities()).resolves.toEqual({});
  });
});
