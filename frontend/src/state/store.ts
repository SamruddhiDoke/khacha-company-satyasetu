import { create } from "zustand";
import {
  api,
  ApiError,
  type Capabilities,
  type Conversation,
  type JobDetail,
  type JobSummary,
  type Language,
  type Message,
  type Preferences,
  type ProgressEvent,
} from "../api/client";
import { dictionaries, type TKey } from "../lib/i18n";

export interface JobState {
  summary: JobSummary;
  detail?: JobDetail;
  events: ProgressEvent[];
}

interface Toast {
  id: number;
  text: string;
  tone: "info" | "error" | "success";
}

interface State {
  ready: boolean;
  caps?: Capabilities;
  prefs: Preferences;
  conversations: Conversation[];
  conversationsLoaded: boolean;
  activeId: string | null;
  messages: Record<string, Message[]>;
  messagesLoading: boolean;
  jobs: Record<string, JobState>;
  msgJob: Record<string, string>; // messageId -> latest jobId
  verifyPending: Record<string, boolean>; // messageId -> request in flight
  panelJobId: string | null;
  correctionJobId: string | null;
  sidebarOpen: boolean;
  sidebarTab: "chats" | "history";
  settingsOpen: boolean;
  sending: boolean;
  waking: boolean; // backend is being retried while it wakes from sleep
  toasts: Toast[];
  draft: string;

  t: (k: TKey) => string;
  init: () => Promise<void>;
  refreshConversations: (q?: string) => Promise<void>;
  selectConversation: (id: string | null) => Promise<void>;
  newConversation: () => Promise<void>;
  deleteConversation: (id: string) => Promise<void>;
  renameConversation: (id: string, title: string) => Promise<void>;
  send: (text: string) => Promise<boolean>;
  upload: (file: File, caption: string) => Promise<boolean>;
  verify: (messageId: string, retry?: boolean) => Promise<void>;
  openPanel: (jobId: string | null) => Promise<void>;
  setPrefs: (p: Partial<Preferences>) => Promise<void>;
  set: (p: Partial<State>) => void;
  toast: (text: string, tone?: Toast["tone"]) => void;
}

const streams = new Map<string, EventSource>();
// Fallback when the live stream cannot be used (e.g. a proxy returned an HTML error page, which makes the
// browser close the EventSource permanently): poll the job until it finishes, with a hard upper bound.
let POLL_MS = 4000;
const POLL_MAX_MS = 10 * 60_000;
const WATCHDOG_MS = 30_000;
export function _setPollMsForTests(ms: number): void {
  POLL_MS = ms;
}
const ACTIVE = new Set(["queued", "running"]);
let toastId = 0;

function errText(e: unknown): string {
  return e instanceof ApiError ? e.message : "Something went wrong.";
}

export const useStore = create<State>((set, get) => {
  const updateJob = (jobId: string, fn: (j: JobState) => JobState) =>
    set((s) => (s.jobs[jobId] ? { jobs: { ...s.jobs, [jobId]: fn(s.jobs[jobId]) } } : {}));

  const registerJob = (summary: JobSummary) =>
    set((s) => {
      const prev = s.jobs[summary.id];
      // Only the latest attempt for a message is shown on that message (no stale attachment).
      const current = s.msgJob[summary.message_id];
      const currentAttempt = current ? s.jobs[current]?.summary.attempt ?? 0 : 0;
      const msgJob = !current || summary.attempt >= currentAttempt
        ? { ...s.msgJob, [summary.message_id]: summary.id } : s.msgJob;
      return { jobs: { ...s.jobs, [summary.id]: { events: prev?.events ?? [], detail: prev?.detail, summary } }, msgJob };
    });

  const loadDetail = async (jobId: string) => {
    try {
      const detail = await api.getVerification(jobId);
      registerJob(detail);
      updateJob(jobId, (j) => ({ ...j, summary: detail, detail, events: mergeEvents(j.events, detail.events) }));
    } catch (e) {
      get().toast(errText(e), "error");
    }
  };

  const isTerminal = (jobId: string) => {
    const st = get().jobs[jobId]?.summary.status;
    return st === "completed" || st === "failed";
  };

  const pollUntilDone = async (jobId: string) => {
    const t0 = Date.now();
    while (Date.now() - t0 < POLL_MAX_MS) {
      await new Promise((r) => setTimeout(r, POLL_MS));
      try {
        const d = await api.getVerification(jobId);
        registerJob(d);
        updateJob(jobId, (j) => ({ ...j, summary: d, detail: d, events: mergeEvents(j.events, d.events) }));
        if (d.status === "completed" || d.status === "failed") {
          void get().refreshConversations();
          return;
        }
      } catch {
        // transient: keep polling until the bound
      }
    }
    get().toast("Lost contact with this check. Reload the page to see its latest status.", "error");
  };

  const stream = (jobId: string) => {
    if (streams.has(jobId)) return;
    const es = new EventSource(api.eventsUrl(jobId)); // the browser resends Last-Event-ID on reconnect
    streams.set(jobId, es);
    // Safety net: even if the stream silently stalls, check the job's real status now and then.
    const watchdog = setInterval(() => {
      if (isTerminal(jobId)) return;
      void api.getVerification(jobId).then((d) => {
        if ((d.status === "completed" || d.status === "failed") && streams.get(jobId) === es) finish();
      }).catch(() => {});
    }, WATCHDOG_MS);
    let finished = false;
    const finish = () => {
      if (finished) return;
      finished = true;
      clearInterval(watchdog);
      es.close();
      streams.delete(jobId);
      void loadDetail(jobId).then(() => get().refreshConversations());
    };
    const onEvent = (ev: MessageEvent) => {
      const data = JSON.parse(ev.data) as ProgressEvent;
      updateJob(jobId, (j) => ({
        ...j,
        events: mergeEvents(j.events, [data]),
        summary: { ...j.summary, status: j.summary.status === "queued" ? "running" : j.summary.status },
      }));
      if (data.kind === "done" || data.kind === "error") finish();
    };
    es.addEventListener("stage", onEvent as EventListener);
    es.addEventListener("done", onEvent as EventListener);
    es.addEventListener("error", (ev) => {
      if ((ev as MessageEvent).data) {
        onEvent(ev as MessageEvent); // server "error" event (job failed)
      } else if (es.readyState === EventSource.CLOSED && !finished) {
        // The browser gave up on the stream (non-stream response such as a proxy 502 page): poll instead.
        finished = true;
        clearInterval(watchdog);
        streams.delete(jobId);
        void pollUntilDone(jobId);
      }
      // otherwise (CONNECTING) the browser reconnects by itself and replays missed events via Last-Event-ID
    });
    es.addEventListener("status", finish); // job already finished (e.g. interrupted by restart)
  };

  return {
    ready: false,
    prefs: { language: "en", theme: "system", explanation_language: null },
    conversations: [],
    conversationsLoaded: false,
    activeId: null,
    messages: {},
    messagesLoading: false,
    jobs: {},
    msgJob: {},
    verifyPending: {},
    panelJobId: null,
    correctionJobId: null,
    sidebarOpen: false,
    sidebarTab: "chats",
    settingsOpen: false,
    sending: false,
    waking: false,
    toasts: [],
    draft: "",

    t: (k) => dictionaries[(get().prefs.language as Language) ?? "en"][k] ?? dictionaries.en[k],
    set: (p) => set(p),

    toast: (text, tone = "info") => {
      const id = ++toastId;
      set((s) => ({ toasts: [...s.toasts, { id, text, tone }] }));
      setTimeout(() => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })), 5000);
    },

    init: async () => {
      const [caps, prefs] = await Promise.allSettled([api.capabilities(), api.getPreferences()]);
      set({
        caps: caps.status === "fulfilled" ? caps.value : undefined,
        prefs: prefs.status === "fulfilled" ? prefs.value : get().prefs,
      });
      if (caps.status === "rejected") get().toast(errText(caps.reason), "error");
      await get().refreshConversations();
      const first = get().conversations[0];
      if (first && window.matchMedia("(min-width: 768px)").matches) await get().selectConversation(first.id);
      set({ ready: true });
    },

    refreshConversations: async (q) => {
      try {
        set({ conversations: await api.listConversations(q), conversationsLoaded: true });
      } catch (e) {
        set({ conversationsLoaded: true });
        get().toast(errText(e), "error");
      }
    },

    selectConversation: async (id) => {
      set({ activeId: id, sidebarOpen: false, panelJobId: null });
      if (!id) return;
      set({ messagesLoading: !get().messages[id] });
      try {
        const msgs = await api.listMessages(id);
        set((s) => ({ messages: { ...s.messages, [id]: msgs }, messagesLoading: false }));
        for (const m of msgs) {
          if (!m.latest_job) continue;
          registerJob(m.latest_job);
          if (ACTIVE.has(m.latest_job.status)) stream(m.latest_job.id);
          else if (!get().jobs[m.latest_job.id]?.detail) void loadDetail(m.latest_job.id);
        }
      } catch (e) {
        set({ messagesLoading: false });
        get().toast(errText(e), "error");
      }
    },

    newConversation: async () => {
      try {
        const c = await api.createConversation();
        set((s) => ({ conversations: [c, ...s.conversations], messages: { ...s.messages, [c.id]: [] } }));
        await get().selectConversation(c.id);
      } catch (e) {
        get().toast(errText(e), "error");
      }
    },

    deleteConversation: async (id) => {
      try {
        await api.deleteConversation(id);
        set((s) => ({
          conversations: s.conversations.filter((c) => c.id !== id),
          activeId: s.activeId === id ? null : s.activeId,
          panelJobId: s.activeId === id ? null : s.panelJobId,
        }));
        get().toast("Conversation and its verification records were deleted.", "success");
      } catch (e) {
        get().toast(errText(e), "error");
      }
    },

    renameConversation: async (id, title) => {
      try {
        const c = await api.renameConversation(id, title);
        set((s) => ({ conversations: s.conversations.map((x) => (x.id === id ? { ...x, title: c.title } : x)) }));
      } catch (e) {
        get().toast(errText(e), "error");
      }
    },

    send: async (text) => {
      const body = text.trim();
      if (!body) return false;
      set({ sending: true });
      try {
        let id = get().activeId;
        if (!id) {
          const c = await api.createConversation();
          set((s) => ({ conversations: [c, ...s.conversations], messages: { ...s.messages, [c.id]: [] }, activeId: c.id }));
          id = c.id;
        }
        const m = await api.sendMessage(id, body);
        set((s) => ({ messages: { ...s.messages, [id!]: [...(s.messages[id!] ?? []), m] } }));
        void get().refreshConversations();
        return true;
      } catch (e) {
        get().toast(errText(e), "error");
        return false;
      } finally {
        set({ sending: false });
      }
    },

    upload: async (file, caption) => {
      set({ sending: true });
      try {
        let id = get().activeId;
        if (!id) {
          const c = await api.createConversation();
          set((s) => ({ conversations: [c, ...s.conversations], messages: { ...s.messages, [c.id]: [] }, activeId: c.id }));
          id = c.id;
        }
        const m = await api.uploadAttachment(id, file, caption);
        set((s) => ({ messages: { ...s.messages, [id!]: [...(s.messages[id!] ?? []), m] } }));
        void get().refreshConversations();
        return true;
      } catch (e) {
        get().toast(errText(e), "error");
        return false;
      } finally {
        set({ sending: false });
      }
    },

    verify: async (messageId, retry = false) => {
      if (get().verifyPending[messageId]) return; // guard against double clicks
      set((s) => ({ verifyPending: { ...s.verifyPending, [messageId]: true } }));
      try {
        const lang = (get().prefs.explanation_language ?? get().prefs.language ?? "en") as Language;
        const job = await api.startVerification(messageId, lang, retry);
        if (job.message_id !== messageId) throw new ApiError(500, "mismatch", "Server returned a job for another message.");
        registerJob(job);
        if (ACTIVE.has(job.status)) stream(job.id);
        else await loadDetail(job.id);
      } catch (e) {
        get().toast(errText(e), "error");
      } finally {
        set((s) => ({ verifyPending: { ...s.verifyPending, [messageId]: false } }));
      }
    },

    openPanel: async (jobId) => {
      set({ panelJobId: jobId });
      if (jobId && !get().jobs[jobId]?.detail) await loadDetail(jobId);
    },

    setPrefs: async (p) => {
      const next = { ...get().prefs, ...p };
      set({ prefs: next });
      try {
        await api.putPreferences(next);
      } catch (e) {
        get().toast(errText(e), "error");
      }
    },
  };
});

export function mergeEvents(a: ProgressEvent[], b: ProgressEvent[]): ProgressEvent[] {
  const byId = new Map<number, ProgressEvent>();
  for (const e of [...a, ...b]) byId.set(e.id, e);
  return [...byId.values()].sort((x, y) => x.seq - y.seq);
}
