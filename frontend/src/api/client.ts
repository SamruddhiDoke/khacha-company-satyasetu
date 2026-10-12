// Typed client for the SatyaSetu backend. All types come from the generated
// OpenAPI schema (src/api/schema.d.ts, `npm run gen:api`), so the contract is
// shared with the FastAPI models instead of being re-declared by hand.
import type { components } from "./schema";

type S = components["schemas"];
export type Conversation = S["ConversationOut"];
export type Message = S["MessageOut"];
export type JobSummary = S["JobSummary"];
export type JobDetail = S["JobDetail"];
export type Claim = S["ClaimOut"];
export type Evidence = S["EvidenceOut"];
export type Source = S["SourceOut"];
export type Finding = S["FindingOut"];
export type HarmSignal = S["HarmSignalOut"];
export type ProgressEvent = S["EventOut"];
export type Correction = S["CorrectionOut"];
export type CorrectionRequest = S["CorrectionRequest"];
export type HistoryItem = S["HistoryItem"];
export type Preferences = S["Preferences"];
export type Capabilities = S["Capabilities"];
export type Usage = S["UsageOut"];
export type Language = "en" | "hi" | "mr";

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message);
  }
}

// --- Connection state (lets the UI show "waking up" instead of an error during a cold start) -------------
type ConnState = "ok" | "waking";
const connListeners = new Set<(s: ConnState) => void>();
export function onConnectionState(fn: (s: ConnState) => void): () => void {
  connListeners.add(fn);
  return () => connListeners.delete(fn);
}
let connState: ConnState = "ok";
let retrying = 0; // requests currently waiting to retry
let slow = 0; // requests still pending after SLOW_MS (a sleeping host holds the connection while it starts)
export const SLOW_MS = 4000;
function publish() {
  const next: ConnState = retrying > 0 || slow > 0 ? "waking" : "ok";
  if (next !== connState) {
    connState = next;
    connListeners.forEach((fn) => fn(next));
  }
}

// Backoff used while the free-tier backend wakes up (~45-60 s observed). Total ~150 s, then give up honestly.
export const RETRY_DELAYS_MS = [2000, 3000, 5000, 8000, 10000, 15000, 15000, 20000, 20000, 25000, 25000];
let sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
export function _setSleepForTests(fn: (ms: number) => Promise<unknown>): void {
  sleep = fn as (ms: number) => Promise<void>;
}

// "unavailable": a non-JSON answer from the hosting layer (proxy error page, host "starting" page) - the request
// never reached SatyaSetu, so even a POST can be resent safely. "network"/"timeout" are only retried for GETs,
// because the server might have processed a write before the connection failed.
function retryable(e: unknown, method: string): boolean {
  if (!(e instanceof ApiError)) return false;
  if (e.code === "unavailable") return true;
  return method === "GET" && (e.code === "network" || e.code === "timeout");
}

async function withRetry<T>(path: string, init: RequestInit): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  let waitingToRetry = false;
  const stopRetrying = () => {
    if (waitingToRetry) {
      waitingToRetry = false;
      retrying -= 1;
      publish();
    }
  };
  for (let attempt = 0; ; attempt++) {
    let isSlow = false;
    const timer = init.body instanceof FormData ? undefined : setTimeout(() => {
      isSlow = true;
      slow += 1;
      publish();
    }, SLOW_MS);
    try {
      const out = await rawRequest<T>(path, init);
      stopRetrying();
      return out;
    } catch (e) {
      if (!retryable(e, method) || attempt >= RETRY_DELAYS_MS.length) {
        stopRetrying();
        if (e instanceof ApiError && attempt > 0 && retryable(e, method)) {
          throw new ApiError(e.status, e.code, "The SatyaSetu server did not come online after about 2 minutes. " +
            "The free hosting may be restarting - please try again shortly.");
        }
        throw e;
      }
      if (!waitingToRetry) {
        waitingToRetry = true;
        retrying += 1;
        publish();
      }
    } finally {
      clearTimeout(timer);
      if (isSlow) {
        slow -= 1;
        publish();
      }
    }
    await sleep(RETRY_DELAYS_MS[attempt]);
  }
}

// The backend creates an anonymous session (HttpOnly cookie) on the first request that has none. If several
// requests are sent before any cookie exists, each creates its own session and the browser keeps whichever
// cookie arrives last - so data created under one session becomes invisible (404) to the next request.
// The first request therefore establishes the session and every other request waits for it.
let sessionReady: Promise<unknown> | null = null;

export function resetSessionGate(): void {
  sessionReady = null; // test hook
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  if (sessionReady === null) {
    const first = withRetry<T>(path, init);
    sessionReady = first.catch(() => {
      sessionReady = null; // failed before a session existed: let the next request try again
    });
    return first;
  }
  await sessionReady;
  return withRetry<T>(path, init);
}

async function rawRequest<T>(path: string, init: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      credentials: "same-origin",
      // Uploads are processed inline (OCR/PDF), so they get longer than ordinary API calls.
      signal: AbortSignal.timeout(init.body instanceof FormData ? 300_000 : 130_000),
      ...init,
      headers: init.body instanceof FormData ? init.headers : { "Content-Type": "application/json", ...init.headers },
    });
  } catch (e) {
    if (e instanceof DOMException && (e.name === "TimeoutError" || e.name === "AbortError")) {
      throw new ApiError(0, "timeout", "The server took too long to respond. It may be waking up - please try again.");
    }
    throw new ApiError(0, "network", "Can't reach SatyaSetu. Please check your internet connection and try again.");
  }
  if (res.status === 204) return undefined as T;
  const isJson = (res.headers.get("content-type") ?? "").includes("application/json");
  if (!isJson) {
    // Every SatyaSetu API response is JSON. Anything else (HTML "starting up" page, proxy error page) came from
    // the hosting layer, not the app - never treat it as data.
    throw new ApiError(res.status, "unavailable", "The SatyaSetu server is starting up or temporarily unavailable.");
  }
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    throw new ApiError(res.status, body?.code ?? "http_error", body?.message ?? `Request failed (${res.status})`);
  }
  return body as T;
}

const json = (method: string, data?: unknown): RequestInit => ({
  method,
  body: data === undefined ? undefined : JSON.stringify(data),
});

export const api = {
  capabilities: () => request<Capabilities>("/api/capabilities"),
  usage: () => request<Usage>("/api/usage"),
  getPreferences: () => request<Preferences>("/api/preferences"),
  putPreferences: (p: Preferences) => request<Preferences>("/api/preferences", json("PUT", p)),

  listConversations: (q?: string) =>
    request<Conversation[]>(`/api/conversations${q ? `?q=${encodeURIComponent(q)}` : ""}`),
  createConversation: () => request<Conversation>("/api/conversations", json("POST", {})),
  renameConversation: (id: string, title: string) =>
    request<Conversation>(`/api/conversations/${id}`, json("PATCH", { title })),
  deleteConversation: (id: string) => request<void>(`/api/conversations/${id}`, { method: "DELETE" }),

  listMessages: (convId: string) => request<Message[]>(`/api/conversations/${convId}/messages`),
  sendMessage: (convId: string, text: string) =>
    request<Message>(`/api/conversations/${convId}/messages`, json("POST", { text })),
  uploadAttachment: (convId: string, file: File, caption: string) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("caption", caption);
    return request<Message>(`/api/conversations/${convId}/attachments`, { method: "POST", body: fd });
  },
  attachmentUrl: (id: string) => `/api/attachments/${id}/file`,

  startVerification: (messageId: string, language: Language, retry = false) =>
    request<JobSummary>(`/api/messages/${messageId}/verifications`, json("POST", { language, retry })),
  getVerification: (jobId: string) => request<JobDetail>(`/api/verifications/${jobId}`),
  eventsUrl: (jobId: string) => `/api/verifications/${jobId}/events`,

  createCorrection: (jobId: string, body: CorrectionRequest) =>
    request<Correction>(`/api/verifications/${jobId}/corrections`, json("POST", body)),

  history: () => request<HistoryItem[]>("/api/history"),
  deleteHistory: (jobId: string) => request<void>(`/api/history/${jobId}`, { method: "DELETE" }),
};
