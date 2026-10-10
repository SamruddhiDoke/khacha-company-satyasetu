import clsx from "clsx";
import { AlertTriangle, CheckCheck, ChevronRight, FileText, Link2, Music, RotateCcw, ShieldAlert, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { api, type Language, type Message } from "../api/client";
import { ERROR_TEXT, STAGES } from "../lib/verdicts";
import { useStore, type JobState } from "../state/store";
import { clockTime, Spinner, VerdictChip } from "./ui";

export default function MessageBubble({ message }: { message: Message }) {
  const s = useStore();
  const lang = (s.prefs.language ?? "en") as Language;
  const jobId = s.msgJob[message.id];
  const job = jobId ? s.jobs[jobId] : undefined;
  // Defensive: never show a job that belongs to a different message.
  const own = job && job.summary.message_id === message.id ? job : undefined;
  const [expanded, setExpanded] = useState(false);
  const long = message.text.length > 700 || message.text.split("\n").length > 14;

  return (
    <li className="flex justify-end animate-fade-up" data-testid="message" data-message-id={message.id}>
      <article
        className={clsx(
          "relative w-fit max-w-[92%] rounded-bubble rounded-tr-md bg-bubble px-3.5 pb-2 pt-2.5 shadow-bubble sm:max-w-[80%]",
          s.panelJobId && own && s.panelJobId === own.summary.id && "ring-2 ring-brand/50",
        )}
      >
        {message.attachment && <AttachmentView message={message} />}
        {message.kind === "url" && (
          <span className="mb-1 inline-flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wide text-brand">
            <Link2 size={12} /> Link
          </span>
        )}
        {message.text && (
          <p className={clsx("whitespace-pre-wrap break-words text-[15px] leading-[1.45]", long && !expanded && "line-clamp-[12]")}>
            {message.text}
          </p>
        )}
        {long && (
          <button onClick={() => setExpanded((x) => !x)} className="mt-1 text-xs font-semibold text-brand">
            {expanded ? "Show less" : "Read more"}
          </button>
        )}
        <div className="mt-1 flex items-center justify-end gap-1 text-[11px] text-ink-3">
          <time dateTime={message.created_at}>{clockTime(message.created_at)}</time>
          <CheckCheck size={14} className="text-brand" aria-label="Sent" />
        </div>
        <VerifyBar messageId={message.id} job={own} lang={lang} />
      </article>
    </li>
  );
}

function VerifyBar({ messageId, job, lang }: { messageId: string; job?: JobState; lang: Language }) {
  const s = useStore();
  const pending = s.verifyPending[messageId];
  const base = "mt-2 border-t border-ink/10 pt-2";

  if (!job) {
    return (
      <div className={base}>
        <button
          onClick={() => void s.verify(messageId)}
          disabled={pending}
          data-testid="verify-button"
          className="focus-ring inline-flex h-8 items-center gap-1.5 rounded-full bg-brand px-3.5 text-[13px] font-semibold text-brand-ink shadow-sm transition hover:brightness-110 active:scale-[0.97] disabled:opacity-60"
        >
          {pending ? <Spinner /> : <ShieldCheck size={15} />} {s.t("verify")}
        </button>
      </div>
    );
  }

  const st = job.summary.status;
  if (st === "queued" || st === "running") {
    const stages = job.events.filter((e) => e.kind === "stage" && e.stage !== "queued");
    const done = new Set(stages.filter((e) => e.status === "completed" || e.status === "skipped").map((e) => e.stage));
    const current = [...stages].reverse().find((e) => e.status === "started" && !done.has(e.stage));
    const label = current ? STAGES.find((x) => x.key === current.stage)?.label ?? current.stage : st === "queued" ? s.t("queued") : "Starting";
    return (
      <div className={base} data-testid="verify-progress" aria-live="polite">
        <div className="flex items-center gap-2 text-[13px] font-medium text-brand">
          <Spinner />
          <span>{label}…</span>
          <span className="ml-auto text-[11px] font-normal text-ink-3">{done.size} step{done.size === 1 ? "" : "s"} done</span>
        </div>
        <div className="mt-1.5 flex gap-1" aria-hidden="true">
          {STAGES.filter((x) => x.key !== "document_checks" && x.key !== "extracting_content").map((x) => (
            <span key={x.key} className={clsx("h-1 flex-1 rounded-full transition-colors",
              done.has(x.key) ? "bg-brand" : current?.stage === x.key ? "bg-brand/40 animate-pulse" : "bg-ink/10")} />
          ))}
        </div>
        <button onClick={() => void s.openPanel(job.summary.id)} className="mt-1.5 text-xs font-semibold text-brand hover:underline">
          {s.t("progress")}
        </button>
      </div>
    );
  }

  if (st === "failed") {
    const code = job.summary.error_code ?? "internal";
    return (
      <div className={base} data-testid="verify-failed">
        <p className="flex items-start gap-1.5 text-[13px] font-medium text-danger">
          <AlertTriangle size={15} className="mt-0.5 shrink-0" />
          <span>{s.t("failed")}: {ERROR_TEXT[code] ?? job.summary.error_message}</span>
        </p>
        <div className="mt-1.5 flex gap-2">
          <button
            onClick={() => void s.verify(messageId, true)}
            disabled={pending}
            className="focus-ring inline-flex h-7 items-center gap-1.5 rounded-full border border-danger/30 px-3 text-xs font-semibold text-danger hover:bg-danger-soft"
          >
            {pending ? <Spinner /> : <RotateCcw size={13} />} {s.t("retry")}
          </button>
          <button onClick={() => void s.openPanel(job.summary.id)} className="text-xs font-semibold text-ink-2 hover:underline">
            Details
          </button>
        </div>
      </div>
    );
  }

  const d = job.detail;
  const harmHigh = d?.harm?.level === "high";
  return (
    <div className={base} data-testid="verify-result">
      <button
        onClick={() => void s.openPanel(job.summary.id)}
        className="focus-ring -mx-1 flex w-[calc(100%+0.5rem)] items-center gap-2 rounded-lg px-1 py-1 text-left hover:bg-ink/5"
      >
        <VerdictChip verdict={job.summary.overall_verdict} lang={lang} />
        {harmHigh && (
          <span className="inline-flex items-center gap-1 rounded-full bg-danger-soft px-2 py-1 text-[11px] font-semibold text-danger">
            <ShieldAlert size={12} /> Risky
          </span>
        )}
        <span className="truncate text-xs text-ink-3">
          {d ? `${d.claims.filter((c) => c.checkable).length} claim(s) · ${d.sources.filter((x) => x.label).length} cited source(s)` : ""}
        </span>
        <span className="ml-auto inline-flex items-center text-xs font-semibold text-brand">
          {s.t("viewReport")} <ChevronRight size={14} />
        </span>
      </button>
    </div>
  );
}

function AttachmentView({ message }: { message: Message }) {
  const a = message.attachment!;
  const [showText, setShowText] = useState(false);
  const [text, setText] = useState<string | null>(null);
  const toggle = async () => {
    if (!showText && text === null) {
      const r = await fetch(`/api/attachments/${a.id}/text`).then((x) => x.json()).catch(() => ({ text: "" }));
      setText(r.text ?? "");
    }
    setShowText((x) => !x);
  };
  const label = a.kind === "audio" ? "transcript" : "extracted text";
  return (
    <div className="mb-1.5">
      {a.kind === "image" ? (
        <img src={api.attachmentUrl(a.id)} alt={a.filename} className="max-h-72 rounded-lg object-contain" loading="lazy" />
      ) : a.kind === "audio" ? (
        <div className="flex items-center gap-2">
          <Music size={18} className="text-brand" />
          <audio controls src={api.attachmentUrl(a.id)} className="h-9 max-w-[260px]" />
        </div>
      ) : (
        <a href={api.attachmentUrl(a.id)} className="flex items-center gap-3 rounded-lg bg-surface/70 px-3 py-2">
          <FileText size={22} className="text-danger" />
          <span className="min-w-0">
            <span className="block truncate text-sm font-medium">{a.filename}</span>
            <span className="block text-xs text-ink-3">PDF · {(a.size_bytes / 1024).toFixed(0)} KB</span>
          </span>
        </a>
      )}
      <div className="mt-1 flex flex-wrap items-center gap-x-2 text-[11px] text-ink-3">
        <span>
          {a.extraction_method === "ocr" ? "OCR" : a.extraction_method === "transcription" ? "Transcribed" : "Text layer"}
          {a.extraction_confidence != null && ` · confidence ${Math.round(a.extraction_confidence)}/100`}
        </span>
        <button onClick={() => void toggle()} className="font-semibold text-brand">
          {showText ? `Hide ${label}` : `Show ${label}`}
        </button>
      </div>
      {a.extraction_warnings.map((w) => (
        <p key={w} className="mt-0.5 text-[11px] text-warn">⚠ {w}</p>
      ))}
      {showText && (
        <pre className="scroll-thin mt-1.5 max-h-48 overflow-auto whitespace-pre-wrap rounded-lg bg-surface/70 p-2 font-sans text-xs text-ink-2">
          {text || "(no text found)"}
        </pre>
      )}
    </div>
  );
}
