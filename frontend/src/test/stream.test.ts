import { afterEach, describe, expect, it, vi } from "vitest";
import { _setSleepForTests, resetSessionGate } from "../api/client";
import { _setPollMsForTests, useStore } from "../state/store";

// Fake EventSource whose request "fails with a non-stream response": the browser closes it for good.
class ClosedEventSource {
  static CONNECTING = 0; static OPEN = 1; static CLOSED = 2;
  readyState = 0;
  private listeners: Record<string, ((e: Event) => void)[]> = {};
  constructor(public url: string) {
    setTimeout(() => {
      this.readyState = 2;
      (this.listeners.error ?? []).forEach((fn) => fn(new Event("error")));
    }, 5);
  }
  addEventListener(t: string, fn: (e: Event) => void) { (this.listeners[t] ??= []).push(fn); }
  close() { this.readyState = 2; }
}

afterEach(() => { vi.unstubAllGlobals(); resetSessionGate(); });

describe("verification progress when the live stream fails", () => {
  it("falls back to polling and shows the final result instead of hanging", async () => {
    _setSleepForTests(() => Promise.resolve());
    _setPollMsForTests(10);
    vi.stubGlobal("EventSource", ClosedEventSource);
    const summary = (status: string, verdict: string | null) => ({
      id: "j1", message_id: "m1", status, attempt: 1, language: "en", overall_verdict: verdict, evidence_strength: null,
      error_code: null, error_message: null, created_at: "", started_at: null, finished_at: null,
    });
    let polls = 0;
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      const body = url.endsWith("/verifications") && init?.method === "POST"
        ? summary("queued", null)
        : url.includes("/api/verifications/j1")
          ? { ...summary(++polls >= 2 ? "completed" : "running", polls >= 2 ? "verified" : null), input_text: "x", conversation_id: "c1",
              explanation: null, harm: null, content_meta: null, models_used: [], usage: {}, claims: [], sources: [], findings: [], events: [] }
          : [];
      return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
    }));
    await useStore.getState().verify("m1");
    await vi.waitFor(() => expect(useStore.getState().jobs.j1?.summary.status).toBe("completed"), { timeout: 2000 });
    expect(useStore.getState().jobs.j1.summary.overall_verdict).toBe("verified");
  });
});
