import clsx from "clsx";
import {
  AlertTriangle, CheckCircle2, ChevronDown, CircleSlash, ExternalLink, FileSearch, HelpCircle, Info, MessageSquareReply,
  RotateCcw, ShieldAlert, X, XCircle,
} from "lucide-react";
import { useState } from "react";
import type { Claim, Evidence, Finding, JobDetail, Language, Source } from "../api/client";
import { ERROR_TEXT, STAGES, STRENGTH_LABEL, TIER_LABEL, VERDICT_HINT, verdictLabel, verdictStyle, type VerdictKey } from "../lib/verdicts";
import { useStore } from "../state/store";
import { clockTime, IconButton, Spinner, VerdictChip } from "./ui";

export default function DetailsPanel({ jobId }: { jobId: string }) {
  const s = useStore();
  const lang = (s.prefs.language ?? "en") as Language;
  const job = s.jobs[jobId];
  const d = job?.detail;
  const status = job?.summary.status;
  const close = () => s.set({ panelJobId: null });

  return (
    <>
      <div className="fixed inset-0 z-30 bg-black/30 lg:hidden" onClick={close} />
      <aside
        aria-label={s.t("report")}
        className="fixed inset-0 z-40 flex flex-col bg-surface animate-slide-in sm:inset-y-0 sm:left-auto sm:w-[460px] sm:border-l sm:border-line sm:shadow-panel lg:static lg:z-auto lg:w-[440px] lg:shadow-none xl:w-[480px]"
      >
        <header className="flex h-16 shrink-0 items-center gap-2 border-b border-line bg-surface-2 px-4">
          <FileSearch size={18} className="text-brand" />
          <h2 className="flex-1 text-[15px] font-semibold">{s.t("report")}</h2>
          {status === "completed" && (
            <button
              onClick={() => s.set({ correctionJobId: jobId })}
              className="focus-ring inline-flex h-9 items-center gap-1.5 rounded-full bg-brand px-3.5 text-[13px] font-semibold text-brand-ink hover:brightness-110"
            >
              <MessageSquareReply size={15} /> <span className="hidden sm:inline">{s.t("correct")}</span>
            </button>
          )}
          <IconButton label={s.t("close")} onClick={close}>
            <X size={19} />
          </IconButton>
        </header>

        <div className="scroll-thin min-h-0 flex-1 overflow-y-auto">
          {!job ? (
            <PanelSkeleton />
          ) : status === "queued" || status === "running" ? (
            <div className="p-5">
              <p className="text-sm text-ink-2">Checking this message now. Each step is marked done only after the server finishes it.</p>
              <Progress events={job.events} />
              <HarmBlock d={d} />
            </div>
          ) : status === "failed" ? (
            <Failed jobId={jobId} />
          ) : !d ? (
            <PanelSkeleton />
          ) : (
            <Report d={d} lang={lang} />
          )}
        </div>
      </aside>
    </>
  );
}

function PanelSkeleton() {
  return (
    <div className="space-y-4 p-5">
      <div className="skeleton h-8 w-40" />
      <div className="skeleton h-20" />
      <div className="skeleton h-32" />
      <div className="skeleton h-32" />
    </div>
  );
}

function Progress({ events }: { events: JobDetail["events"] }) {
  const stages = events.filter((e) => e.kind === "stage" && e.stage !== "queued");
  const byStage = new Map<string, { status: string; detail: string | null; at: string }>();
  for (const e of stages) byStage.set(e.stage!, { status: e.status!, detail: e.detail, at: e.at });
  const shown = STAGES.filter((st) => byStage.has(st.key));
  const errorEv = events.find((e) => e.kind === "error");
  return (
    <ol className="mt-4 space-y-2.5" aria-live="polite">
      {shown.map((st) => {
        const info = byStage.get(st.key)!;
        return (
          <li key={st.key} className="flex items-start gap-3">
            <span className="mt-0.5">
              {info.status === "completed" || info.status === "skipped" ? <CheckCircle2 size={17} className="text-brand" />
                : info.status === "failed" ? <XCircle size={17} className="text-danger" /> : <Spinner className="text-brand" />}
            </span>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium">{st.label}</p>
              {info.detail && <p className="text-xs text-ink-3">{info.detail}</p>}
            </div>
            <time className="text-[11px] text-ink-3">{clockTime(info.at)}</time>
          </li>
        );
      })}
      {!shown.length && !errorEv && <li className="text-sm text-ink-3">Waiting for the server to start…</li>}
    </ol>
  );
}

function Failed({ jobId }: { jobId: string }) {
  const s = useStore();
  const job = s.jobs[jobId];
  const code = job.summary.error_code ?? "internal";
  return (
    <div className="space-y-4 p-5">
      <div className="rounded-xl border border-danger/25 bg-danger-soft p-4">
        <p className="flex items-center gap-2 font-semibold text-danger"><AlertTriangle size={17} /> {s.t("failed")}</p>
        <p className="mt-1 text-sm text-ink-2">{ERROR_TEXT[code] ?? "The check could not be completed."}</p>
        {job.summary.error_message && <p className="mt-2 text-xs text-ink-3">Server detail: {job.summary.error_message}</p>}
        <p className="mt-2 text-xs text-ink-3">No verdict was produced. A failed check never shows a result.</p>
        <button
          onClick={() => void s.verify(job.summary.message_id, true)}
          className="focus-ring mt-3 inline-flex h-8 items-center gap-1.5 rounded-full bg-danger px-3.5 text-xs font-semibold text-white"
        >
          <RotateCcw size={13} /> {s.t("retry")}
        </button>
      </div>
      <Progress events={job.detail?.events ?? job.events} />
      <HarmBlock d={job.detail} />
      {job.detail && job.detail.findings.length > 0 && <Findings findings={job.detail.findings} />}
    </div>
  );
}

function Report({ d, lang }: { d: JobDetail; lang: Language }) {
  const s = useStore();
  const verdict = (d.overall_verdict ?? "insufficient_evidence") as VerdictKey;
  const st = verdictStyle(verdict);
  const checkable = d.claims.filter((c) => c.checkable);
  const counts = new Map<string, number>();
  checkable.forEach((c) => counts.set(c.verdict!, (counts.get(c.verdict!) ?? 0) + 1));
  const fetched = d.sources.filter((x) => x.fetch_ok).length;
  const ex = d.explanation as Record<string, any> | null;
  const srcById = new Map(d.sources.map((x) => [x.id, x]));

  return (
    <div className="space-y-5 p-5">
      {/* Verdict hero */}
      <section className="overflow-hidden rounded-2xl border border-line">
        <div className={clsx("h-1.5", st.bar)} />
        <div className="p-4">
          <p className="text-xs font-semibold uppercase tracking-wide text-ink-3">{s.t("overall")}</p>
          <div className="mt-1.5 flex flex-wrap items-center gap-2">
            <span className="text-2xl font-bold tracking-tight">{verdictLabel(verdict, lang)}</span>
          </div>
          <p className="mt-1 text-sm text-ink-2">{VERDICT_HINT[verdict]}</p>
          <dl className="mt-4 grid grid-cols-3 gap-2 text-center">
            <Stat label={s.t("evidenceStrength")} value={<Strength value={d.evidence_strength ?? "none"} />} />
            <Stat label={s.t("claims")} value={`${checkable.length}${d.claims.length > checkable.length ? ` / ${d.claims.length}` : ""}`} />
            <Stat label={s.t("sourcesChecked")} value={`${fetched} / ${d.sources.length}`} />
          </dl>
          {counts.size > 1 && (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {[...counts].map(([v, n]) => (
                <span key={v} className="text-xs text-ink-2"><VerdictChip verdict={v} lang={lang} size="sm" /> ×{n}</span>
              ))}
            </div>
          )}
          <p className="mt-3 text-[11px] text-ink-3">
            {s.t("lastChecked")} {d.finished_at ? new Date(d.finished_at).toLocaleString() : ""}
          </p>
        </div>
      </section>

      <HarmBlock d={d} />

      {/* Explanation */}
      {ex && (
        <section>
          <SectionTitle>Summary</SectionTitle>
          <p className="text-[14.5px] leading-relaxed">{ex.summary}</p>
          {ex.uncertainty && <Note icon={<HelpCircle size={15} />} title={s.t("uncertainty")}>{ex.uncertainty}</Note>}
          {ex.missing_context && <Note icon={<Info size={15} />} title={s.t("missingContext")}>{ex.missing_context}</Note>}
          {ex.what_would_change && <Note icon={<FileSearch size={15} />} title={s.t("whatWouldChange")}>{ex.what_would_change}</Note>}
          {ex.source === "template" && (
            <p className="mt-2 text-[11px] text-ink-3">Explanation built from the structured findings (the language model was not used for this step{ex.fallback_reason ? `: ${ex.fallback_reason}` : ""}).</p>
          )}
        </section>
      )}

      {/* Claims */}
      <section>
        <SectionTitle>{s.t("claims")} ({d.claims.length})</SectionTitle>
        <div className="space-y-3">
          {d.claims.map((c) => (
            <ClaimCard key={c.id} c={c} lang={lang} srcById={srcById} perClaim={ex?.per_claim?.[String(c.idx)]} />
          ))}
          {!d.claims.length && <p className="text-sm text-ink-3">{ex?.note ?? "No checkable statements were found."}</p>}
        </div>
      </section>

      {d.findings.length > 0 && <Findings findings={d.findings} />}

      {/* Sources */}
      <section>
        <SectionTitle>{s.t("sources")} ({d.sources.length})</SectionTitle>
        <ul className="space-y-2">
          {d.sources.map((x) => <SourceRow key={x.id} x={x} />)}
          {!d.sources.length && <p className="text-sm text-ink-3">No sources were retrieved for this message.</p>}
        </ul>
      </section>

      <Meta d={d} />
    </div>
  );
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-xl bg-sunken px-2 py-2.5">
      <dd className="text-[15px] font-bold">{value}</dd>
      <dt className="mt-0.5 text-[10.5px] font-medium uppercase tracking-wide text-ink-3">{label}</dt>
    </div>
  );
}

function Strength({ value }: { value: string }) {
  const n = { none: 0, weak: 1, moderate: 2, strong: 3 }[value] ?? 0;
  return (
    <span className="inline-flex flex-col items-center gap-1">
      <span>{STRENGTH_LABEL[value] ?? value}</span>
      <span className="flex gap-0.5" aria-hidden="true">
        {[1, 2, 3].map((i) => <span key={i} className={clsx("h-1 w-4 rounded-full", i <= n ? "bg-brand" : "bg-ink/15")} />)}
      </span>
    </span>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h3 className="mb-2 text-xs font-bold uppercase tracking-wide text-ink-3">{children}</h3>;
}

function Note({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <div className="mt-3 flex gap-2.5 rounded-xl bg-sunken px-3 py-2.5">
      <span className="mt-0.5 text-ink-3">{icon}</span>
      <div>
        <p className="text-xs font-semibold text-ink-2">{title}</p>
        <p className="text-[13.5px] leading-relaxed text-ink">{children}</p>
      </div>
    </div>
  );
}

function HarmBlock({ d }: { d?: JobDetail }) {
  const t = useStore((s) => s.t);
  const signals = d?.harm?.signals ?? [];
  if (!signals.length) return null;
  return (
    <section className="rounded-2xl border border-danger/20 bg-danger-soft/60 p-4">
      <p className="flex items-center gap-2 text-sm font-semibold text-danger"><ShieldAlert size={17} /> {t("safety")}</p>
      <p className="mt-0.5 text-[11px] text-ink-3">About acting on this message - separate from whether its claims are true.</p>
      <ul className="mt-2.5 space-y-2.5">
        {signals.map((sig, i) => (
          <li key={i} className="text-[13.5px]">
            <span className="font-semibold">{sig.title}</span>
            <span className={clsx("ml-2 rounded px-1.5 py-0.5 text-[10px] font-bold uppercase",
              sig.severity === "high" ? "bg-danger text-white" : sig.severity === "medium" ? "bg-warn/20 text-warn" : "bg-ink/10 text-ink-2")}>
              {sig.severity}
            </span>
            <p className="mt-0.5 text-ink-2">{sig.detail}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}

const STANCE_STYLE: Record<string, string> = {
  supports: "text-emerald-700 dark:text-emerald-400",
  refutes: "text-rose-700 dark:text-rose-400",
  partially_supports: "text-amber-700 dark:text-amber-400",
  not_relevant: "text-ink-3",
};

function ClaimCard({ c, lang, srcById, perClaim }:
  { c: Claim; lang: Language; srcById: Map<string, Source>; perClaim?: string }) {
  const t = useStore((s) => s.t);
  const [showRejected, setShowRejected] = useState(false);
  const counted = c.evidence.filter((e) => e.counted);
  const rejected = c.evidence.filter((e) => !e.counted && e.stance !== "not_relevant");
  return (
    <article className="rounded-2xl border border-line p-4">
      <div className="flex items-start justify-between gap-3">
        <p className="text-[14.5px] font-medium leading-snug">“{c.original_text}”</p>
        {c.checkable ? <VerdictChip verdict={c.verdict} lang={lang} size="sm" /> : (
          <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-sunken px-2 py-0.5 text-[11px] font-semibold text-ink-3">
            <CircleSlash size={11} /> {t("notCheckable")}
          </span>
        )}
      </div>
      {c.normalized && c.normalized !== c.original_text.replace(/\.$/, "") && (
        <p className="mt-1 text-xs text-ink-3">Checked as: {c.normalized}</p>
      )}
      {!c.checkable ? (
        <p className="mt-2 text-[13px] text-ink-2">{c.reason_not_checkable ?? c.verdict_reason} <span className="text-ink-3">({c.claim_type})</span></p>
      ) : (
        <>
          <p className="mt-2 text-[13.5px] text-ink-2">{perClaim || c.verdict_reason}</p>
          <p className="mt-1 text-[11px] text-ink-3">
            Evidence strength: {STRENGTH_LABEL[c.evidence_strength ?? "none"]} · rule: {c.verdict_reason}
          </p>
          {c.conflict_note && <p className="mt-2 text-[13px] font-medium text-violet-700 dark:text-violet-300">{c.conflict_note}</p>}
          {c.missing_context && <Note icon={<Info size={15} />} title={t("missingContext")}>{c.missing_context}</Note>}
          {counted.length > 0 && (
            <ul className="mt-3 space-y-2.5">
              {counted.map((e) => <EvidenceItem key={e.id} e={e} src={srcById.get(e.source_id)} />)}
            </ul>
          )}
          {!counted.length && (
            <p className="mt-3 rounded-lg bg-sunken px-3 py-2 text-[13px] text-ink-2">
              No retrieved source contained a verifiable passage addressing this claim. That is not evidence that it is false.
            </p>
          )}
          {rejected.length > 0 && (
            <div className="mt-2">
              <button onClick={() => setShowRejected((x) => !x)} className="inline-flex items-center gap-1 text-xs font-semibold text-ink-3 hover:text-ink">
                <ChevronDown size={13} className={clsx("transition", showRejected && "rotate-180")} />
                {rejected.length} assessment(s) not counted
              </button>
              {showRejected && (
                <ul className="mt-2 space-y-2">
                  {rejected.map((e) => (
                    <li key={e.id} className="rounded-lg border border-dashed border-line px-3 py-2 text-xs text-ink-3">
                      <span className="font-semibold">{t(e.stance as any)}</span> per {srcById.get(e.source_id)?.domain}: {e.rejected_reason}
                      {e.quote && <span className="mt-1 block italic line-through">“{e.quote}”</span>}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
          {c.what_would_change && <p className="mt-3 text-xs text-ink-3"><span className="font-semibold">{t("whatWouldChange")}:</span> {c.what_would_change}</p>}
        </>
      )}
    </article>
  );
}

function EvidenceItem({ e, src }: { e: Evidence; src?: Source }) {
  const t = useStore((s) => s.t);
  return (
    <li className="rounded-xl bg-sunken p-3">
      <div className="flex items-center gap-2 text-xs">
        <span className={clsx("font-bold", STANCE_STYLE[e.stance])}>{t(e.stance as any)}</span>
        {e.temporal_issue && <span className="rounded bg-indigo-500/10 px-1.5 text-[10px] font-semibold text-indigo-600">dated</span>}
        <span className="ml-auto text-ink-3">{src?.label && `[${src.label}] `}{src?.publisher || src?.domain}</span>
      </div>
      <blockquote className="mt-1.5 border-l-2 border-brand/40 pl-3 text-[14px] leading-relaxed text-ink">“{e.quote}”</blockquote>
      {e.rationale && <p className="mt-1.5 text-xs text-ink-2">{e.rationale}</p>}
      {src && (
        <a href={src.final_url ?? src.url} target="_blank" rel="noopener noreferrer nofollow"
           className="mt-1.5 inline-flex items-center gap-1 text-xs font-semibold text-brand hover:underline">
          {t("openSource")} <ExternalLink size={12} />
        </a>
      )}
      <p className="mt-1 text-[10.5px] text-ink-3">Quote verified against the retrieved page text.</p>
    </li>
  );
}

function SourceRow({ x }: { x: Source }) {
  return (
    <li className={clsx("rounded-xl border border-line px-3 py-2.5", !x.fetch_ok && "opacity-70")}>
      <div className="flex items-center gap-2">
        {x.label && <span className="rounded bg-brand-soft px-1.5 py-0.5 text-[11px] font-bold text-brand">{x.label}</span>}
        <span className="rounded bg-sunken px-1.5 py-0.5 text-[10.5px] font-semibold text-ink-2">{TIER_LABEL[x.tier] ?? x.tier}</span>
        <span className="truncate text-xs text-ink-3">{x.domain}</span>
      </div>
      <a href={x.final_url ?? x.url} target="_blank" rel="noopener noreferrer nofollow"
         className="mt-1 line-clamp-2 block text-[13.5px] font-medium hover:text-brand hover:underline">
        {x.title || x.url}
      </a>
      <p className="mt-1 text-[11px] text-ink-3">
        {x.fetch_ok
          ? `Retrieved ${x.retrieval_method === "direct" ? "directly" : "via search provider"}${x.retrieved_at ? ` · ${clockTime(x.retrieved_at)}` : ""}`
          : `Not used - ${x.fetch_error ?? "could not be retrieved"}`}
        {x.published_date && ` · published ${x.published_date.slice(0, 10)}`}
        {x.factcheck_rating && ` · fact-check rating: ${x.factcheck_rating}`}
      </p>
    </li>
  );
}

const FINDING_META: Record<string, { label: string; cls: string }> = {
  confirmed_inconsistency: { label: "Confirmed inconsistency", cls: "text-danger" },
  warning: { label: "Warning sign", cls: "text-warn" },
  could_not_check: { label: "Could not check", cls: "text-ink-3" },
  passed: { label: "Check passed", cls: "text-emerald-600 dark:text-emerald-400" },
};

function Findings({ findings }: { findings: Finding[] }) {
  const t = useStore((s) => s.t);
  return (
    <section>
      <SectionTitle>{t("documentChecks")}</SectionTitle>
      <p className="mb-2 text-xs text-ink-3">A warning sign is not proof of forgery. A reference number that could not be checked is not evidence of fraud.</p>
      <ul className="space-y-2">
        {findings.map((f) => (
          <li key={f.id} className="rounded-xl border border-line px-3 py-2.5">
            <p className={clsx("text-[11px] font-bold uppercase tracking-wide", FINDING_META[f.category]?.cls)}>
              {FINDING_META[f.category]?.label ?? f.category}
            </p>
            <p className="mt-0.5 text-[13.5px] font-medium">{f.title}</p>
            <p className="text-[13px] text-ink-2">{f.detail}</p>
            {f.location?.snippet && (
              <p className="mt-1 rounded bg-sunken px-2 py-1 font-mono text-[11px] text-ink-2">
                {f.location.page ? `p.${f.location.page}: ` : ""}{String(f.location.snippet)}
              </p>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

function Meta({ d }: { d: JobDetail }) {
  const meta = (d.content_meta ?? {}) as Record<string, any>;
  const usage = d.usage as Record<string, number>;
  return (
    <section className="rounded-xl bg-sunken px-3 py-3 text-[11.5px] leading-relaxed text-ink-3">
      <p className="font-semibold text-ink-2">About this check</p>
      <p>Models: {d.models_used.join(", ") || "none"} · LLM calls: {usage.llm_calls ?? 0} · searches: {usage.searches ?? 0} · pages fetched: {usage.fetches ?? 0}</p>
      {meta.linked_pages?.length > 0 && (
        <p>Linked pages: {meta.linked_pages.map((p: any) => `${p.url} (${p.status}${p.reason ? `: ${p.reason}` : ""})`).join("; ")}</p>
      )}
      {meta.ai_instruction_detected && <p>The message contained instructions aimed at AI systems; they were ignored.</p>}
      <p className="mt-1">Independent automated fact-check summary. It can be incomplete or wrong; check the cited sources.</p>
    </section>
  );
}
