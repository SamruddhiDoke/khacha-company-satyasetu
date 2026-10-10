import clsx from "clsx";
import { History, MessageSquarePlus, MessagesSquare, Search, Settings, Trash2, X } from "lucide-react";
import { useEffect, useState } from "react";
import { api, type HistoryItem, type Language } from "../api/client";
import { useStore } from "../state/store";
import { IconButton, Logo, relTime, VerdictChip } from "./ui";

const LANGS: { code: Language; label: string }[] = [
  { code: "en", label: "English" },
  { code: "hi", label: "हिन्दी" },
  { code: "mr", label: "मराठी" },
];

export default function Sidebar() {
  const s = useStore();
  const lang = (s.prefs.language ?? "en") as Language;
  const [q, setQ] = useState("");

  useEffect(() => {
    const h = setTimeout(() => void s.refreshConversations(q || undefined), 200);
    return () => clearTimeout(h);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q]);

  return (
    <>
      {s.sidebarOpen && (
        <div className="fixed inset-0 z-30 bg-black/40 md:hidden" onClick={() => s.set({ sidebarOpen: false })} />
      )}
      <aside
        aria-label="Conversations"
        className={clsx(
          "fixed inset-y-0 left-0 z-40 flex w-[86vw] max-w-[340px] flex-col border-r border-line bg-surface transition-transform duration-200",
          "md:static md:z-auto md:w-[320px] md:max-w-none md:translate-x-0 lg:w-[360px]",
          s.sidebarOpen ? "translate-x-0 shadow-pop" : "-translate-x-full",
        )}
      >
        <header className="flex items-center gap-3 px-4 pb-3 pt-4">
          <Logo size={38} />
          <div className="min-w-0 flex-1">
            <h1 className="text-[17px] font-bold leading-tight tracking-tight">SatyaSetu</h1>
            <p className="truncate text-xs text-ink-3">{s.t("tagline")}</p>
          </div>
          <IconButton label={s.t("newChat")} onClick={() => void s.newConversation()} className="text-brand">
            <MessageSquarePlus size={20} />
          </IconButton>
          <IconButton label={s.t("close")} onClick={() => s.set({ sidebarOpen: false })} className="md:hidden">
            <X size={20} />
          </IconButton>
        </header>

        <div className="px-4 pb-2">
          <label className="flex h-10 items-center gap-2 rounded-xl bg-sunken px-3 text-ink-3 focus-within:ring-2 focus-within:ring-brand/40">
            <Search size={16} />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder={s.t("searchChats")}
              className="h-full w-full bg-transparent text-sm text-ink placeholder:text-ink-3 focus:outline-none"
            />
          </label>
        </div>

        <nav className="flex gap-1 px-4 pb-2" aria-label="Sidebar sections">
          {(["chats", "history"] as const).map((tab) => (
            <button
              key={tab}
              onClick={() => s.set({ sidebarTab: tab })}
              className={clsx(
                "focus-ring flex h-8 items-center gap-1.5 rounded-full px-3 text-xs font-semibold transition-colors",
                s.sidebarTab === tab ? "bg-brand-soft text-brand" : "text-ink-2 hover:bg-sunken",
              )}
              aria-pressed={s.sidebarTab === tab}
            >
              {tab === "chats" ? <MessagesSquare size={14} /> : <History size={14} />}
              {s.t(tab)}
            </button>
          ))}
        </nav>

        <div className="scroll-thin min-h-0 flex-1 overflow-y-auto">
          {s.sidebarTab === "chats" ? <ConversationList /> : <HistoryList />}
        </div>

        <footer className="flex items-center gap-2 border-t border-line px-3 py-2.5">
          <select
            aria-label={s.t("language")}
            value={lang}
            onChange={(e) => void s.setPrefs({ language: e.target.value as Language })}
            className="focus-ring h-9 flex-1 rounded-lg border border-line bg-surface px-2 text-sm"
          >
            {LANGS.map((l) => (
              <option key={l.code} value={l.code}>{l.label}</option>
            ))}
          </select>
          <button
            onClick={() => s.set({ settingsOpen: true })}
            className="focus-ring flex h-9 items-center gap-2 rounded-lg px-3 text-sm font-medium text-ink-2 hover:bg-sunken"
          >
            <Settings size={16} /> {s.t("settings")}
          </button>
        </footer>
      </aside>
    </>
  );
}

function ConversationList() {
  const s = useStore();
  const lang = (s.prefs.language ?? "en") as Language;
  if (!s.conversationsLoaded) {
    return (
      <div className="space-y-3 px-4 py-2">
        {[0, 1, 2].map((i) => (
          <div key={i} className="flex gap-3">
            <div className="skeleton h-11 w-11 rounded-full" />
            <div className="flex-1 space-y-2 py-1"><div className="skeleton h-3 w-2/3" /><div className="skeleton h-3 w-full" /></div>
          </div>
        ))}
      </div>
    );
  }
  if (!s.conversations.length) {
    return (
      <div className="px-6 py-10 text-center">
        <p className="text-sm font-medium text-ink-2">{s.t("noChats")}</p>
        <p className="mt-1 text-xs text-ink-3">{s.t("noChatsHint")}</p>
      </div>
    );
  }
  return (
    <ul className="px-2 pb-2">
      {s.conversations.map((c) => {
        const active = c.id === s.activeId;
        const running = c.last_status === "running" || c.last_status === "queued";
        return (
          <li key={c.id} className="group relative">
            <button
              onClick={() => void s.selectConversation(c.id)}
              className={clsx(
                "focus-ring flex w-full items-center gap-3 rounded-xl px-2.5 py-2.5 text-left transition-colors",
                active ? "bg-brand-soft/70" : "hover:bg-sunken",
              )}
              aria-current={active ? "page" : undefined}
            >
              <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-sunken text-sm font-bold text-brand">
                {(c.title || "?").trim().charAt(0).toUpperCase()}
              </span>
              <span className="min-w-0 flex-1">
                <span className="flex items-baseline justify-between gap-2">
                  <span className="truncate text-[14.5px] font-semibold">{c.title}</span>
                  <span className="shrink-0 text-[11px] text-ink-3">{relTime(c.updated_at)}</span>
                </span>
                <span className="mt-0.5 flex items-center justify-between gap-2">
                  <span className="truncate text-[13px] text-ink-3">{c.last_message_preview || "No messages yet"}</span>
                  {running ? (
                    <span className="h-2 w-2 shrink-0 animate-pulse rounded-full bg-brand" aria-label="Check running" />
                  ) : c.last_status === "failed" ? (
                    <span className="shrink-0 text-[11px] font-semibold text-danger">Failed</span>
                  ) : (
                    <VerdictChip verdict={c.last_verdict} lang={lang} size="sm" />
                  )}
                </span>
              </span>
            </button>
            <button
              onClick={() => confirm(`${s.t("deleteChat")}? This also deletes its verification records.`) && void s.deleteConversation(c.id)}
              className="focus-ring absolute right-2 top-2 hidden h-7 w-7 items-center justify-center rounded-md bg-surface text-ink-3 shadow-sm hover:text-danger group-hover:flex focus:flex"
              aria-label={`${s.t("deleteChat")}: ${c.title}`}
            >
              <Trash2 size={14} />
            </button>
          </li>
        );
      })}
    </ul>
  );
}

function HistoryList() {
  const s = useStore();
  const lang = (s.prefs.language ?? "en") as Language;
  const [items, setItems] = useState<HistoryItem[] | null>(null);
  const load = () => api.history().then(setItems).catch(() => setItems([]));
  // Reload when a job is created or finishes, not on every progress event.
  const finishedKey = Object.values(s.jobs).map((j) => `${j.summary.id}:${j.summary.status === "completed" || j.summary.status === "failed"}`).join();
  useEffect(() => {
    void load();
  }, [finishedKey]);

  if (!items) return <div className="space-y-3 px-4 py-2">{[0, 1, 2].map((i) => <div key={i} className="skeleton h-14" />)}</div>;
  if (!items.length) return <p className="px-6 py-10 text-center text-sm text-ink-3">{s.t("noHistory")}</p>;
  return (
    <ul className="space-y-1 px-2 pb-2">
      {items.map((h) => (
        <li key={h.job.id} className="group relative">
          <button
            onClick={async () => {
              await s.selectConversation(h.conversation_id);
              await s.openPanel(h.job.id);
            }}
            className="focus-ring w-full rounded-xl px-3 py-2.5 text-left hover:bg-sunken"
          >
            <div className="flex items-center justify-between gap-2">
              {h.job.status === "completed" ? (
                <VerdictChip verdict={h.job.overall_verdict} lang={lang} size="sm" />
              ) : (
                <span className={clsx("text-[11px] font-semibold", h.job.status === "failed" ? "text-danger" : "text-brand")}>
                  {h.job.status === "failed" ? s.t("failed") : s.t("verifying")}
                </span>
              )}
              <span className="text-[11px] text-ink-3">{relTime(h.job.created_at)}</span>
            </div>
            <p className="mt-1 line-clamp-2 text-[13px] text-ink-2">{h.message_preview}</p>
            <p className="mt-0.5 truncate text-[11px] text-ink-3">{h.conversation_title} · {h.claim_count} claim(s)</p>
          </button>
          <button
            onClick={async () => {
              await api.deleteHistory(h.job.id).catch((e) => s.toast(e.message, "error"));
              void load();
            }}
            className="focus-ring absolute bottom-2 right-2 hidden h-7 w-7 items-center justify-center rounded-md text-ink-3 hover:text-danger group-hover:flex focus:flex"
            aria-label="Delete this check from history"
          >
            <Trash2 size={14} />
          </button>
        </li>
      ))}
    </ul>
  );
}
