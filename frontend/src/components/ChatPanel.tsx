import { KeyRound, Menu, ShieldCheck } from "lucide-react";
import { useEffect, useLayoutEffect, useRef } from "react";
import type { Language } from "../api/client";
import { useStore } from "../state/store";
import Composer from "./Composer";
import MessageBubble from "./MessageBubble";
import { IconButton, Logo } from "./ui";

// Optional starting points. They only fill the composer; nothing is sent or verified until the user acts,
// and they have no special handling anywhere in the backend.
const SUGGESTIONS = [
  "Forwarded as received: From 1st next month all bank accounts without PAN linked will be frozen by RBI. Share with family.",
  "Boiling water with clove and camphor cures dengue in 3 days, doctors are hiding this.",
  "The Indian Constitution came into effect on 26 January 1950.",
];

export default function ChatPanel() {
  const s = useStore();
  const lang = (s.prefs.language ?? "en") as Language;
  const conv = s.conversations.find((c) => c.id === s.activeId);
  const messages = s.activeId ? s.messages[s.activeId] ?? [] : [];
  const scroller = useRef<HTMLDivElement>(null);
  const lastCount = useRef(0);

  useLayoutEffect(() => {
    const el = scroller.current;
    if (!el) return;
    if (messages.length !== lastCount.current) el.scrollTo({ top: el.scrollHeight });
    lastCount.current = messages.length;
  }, [messages.length, s.activeId]);

  useEffect(() => {
    lastCount.current = 0;
  }, [s.activeId]);

  const liveOff = s.caps && !s.caps.live_verification;

  return (
    <section className="flex min-w-0 flex-1 flex-col" aria-label="Chat">
      <header className="z-10 flex h-16 shrink-0 items-center gap-3 border-b border-line bg-surface-2 px-3 md:px-5">
        <IconButton label="Open conversations" onClick={() => s.set({ sidebarOpen: true })} className="md:hidden">
          <Menu size={20} />
        </IconButton>
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-brand-soft text-brand">
          <ShieldCheck size={20} />
        </div>
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-[15px] font-semibold">{conv?.title ?? "SatyaSetu"}</h2>
          <p className="truncate text-xs text-ink-3">
            {conv ? `${messages.length} message${messages.length === 1 ? "" : "s"} · tap Verify on any message` : s.t("tagline")}
          </p>
        </div>
      </header>

      {liveOff && (
        <div role="status" className="flex items-start gap-3 border-b border-warn/20 bg-warn-soft px-4 py-2.5 text-[13px] text-warn md:px-6">
          <KeyRound size={16} className="mt-0.5 shrink-0" />
          <p>
            <span className="font-semibold">{s.t("setupNeeded")}.</span> {s.t("setupBody")}{" "}
            <button className="font-semibold underline underline-offset-2" onClick={() => s.set({ settingsOpen: true })}>
              {s.t("settings")}
            </button>
          </p>
        </div>
      )}

      <div ref={scroller} className="chat-wallpaper scroll-thin min-h-0 flex-1 overflow-y-auto">
        {s.activeId && s.messagesLoading ? (
          <div className="mx-auto flex max-w-3xl flex-col gap-4 px-4 py-6">
            <div className="skeleton ml-auto h-16 w-2/3 rounded-bubble" />
            <div className="skeleton ml-auto h-24 w-1/2 rounded-bubble" />
          </div>
        ) : messages.length === 0 ? (
          <EmptyState onPick={(t) => s.set({ draft: t })} lang={lang} />
        ) : (
          <ol className="mx-auto flex max-w-3xl flex-col gap-3 px-3 py-5 md:px-6" aria-live="polite">
            {messages.map((m) => (
              <MessageBubble key={m.id} message={m} />
            ))}
          </ol>
        )}
      </div>

      <Composer />
    </section>
  );
}

function EmptyState({ onPick }: { onPick: (t: string) => void; lang: Language }) {
  const t = useStore((s) => s.t);
  return (
    <div className="mx-auto flex min-h-full max-w-xl flex-col items-center justify-center px-6 py-10 text-center animate-fade-up">
      <Logo size={56} />
      <h3 className="mt-5 text-xl font-bold tracking-tight">{t("emptyTitle")}</h3>
      <p className="mt-2 text-[14.5px] leading-relaxed text-ink-2">{t("emptyBody")}</p>
      <div className="mt-6 grid w-full grid-cols-3 gap-2 text-left text-xs">
        {[
          ["1", "Paste & send"],
          ["2", "Tap Verify"],
          ["3", "Read the evidence"],
        ].map(([n, label]) => (
          <div key={n} className="rounded-xl border border-line bg-surface/80 px-3 py-2.5">
            <span className="text-[11px] font-bold text-brand">STEP {n}</span>
            <p className="mt-0.5 font-medium text-ink">{label}</p>
          </div>
        ))}
      </div>
      <p className="mt-8 text-xs font-medium uppercase tracking-wide text-ink-3">{t("examplesLabel")}</p>
      <div className="mt-2 flex w-full flex-col gap-2">
        {SUGGESTIONS.map((sug) => (
          <button
            key={sug}
            onClick={() => onPick(sug)}
            className="focus-ring rounded-xl border border-line bg-surface/90 px-4 py-2.5 text-left text-[13px] leading-snug text-ink-2 transition-colors hover:border-brand/40 hover:text-ink"
          >
            {sug}
          </button>
        ))}
      </div>
    </div>
  );
}
