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
    const first = rawRequest<T>(path, init);
    sessionReady = first.catch(() => {
      sessionReady = null; // failed before a session existed: let the next request try again
    });
    return first;
  }
  await sessionReady;
  return rawRequest<T>(path, init);
}

async function rawRequest<T>(path: string, init: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      credentials: "same-origin",
      // Generous: a sleeping free-tier backend can take about a minute to wake, and uploads are processed inline.
      signal: AbortSignal.timeout(init.body instanceof FormData ? 300_000 : 130_000),
      ...init,
      headers: init.body instanceof FormData ? init.headers : { "Content-Type": "application/json", ...init.headers },
    });
  } catch (e) {
    if (e instanceof DOMException && (e.name === "TimeoutError" || e.name === "AbortError")) {
      throw new ApiError(0, "timeout", "The server took too long to respond. It may be waking up - please try again.");
    }
    throw new ApiError(0, "network", "Cannot reach the SatyaSetu server. Check your connection and try again.");
  }
  const isJson = (res.headers.get("content-type") ?? "").includes("application/json");
  if (!isJson && (res.status === 502 || res.status === 503 || res.status === 504)) {
    throw new ApiError(res.status, "unavailable", "The SatyaSetu server is unavailable or starting up. Please try again shortly.");
  }
  if (res.status === 204) return undefined as T;
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
