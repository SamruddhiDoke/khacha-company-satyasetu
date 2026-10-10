import clsx from "clsx";
import { toPng } from "html-to-image";
import { Check, Copy, Download, Share2, Sparkles } from "lucide-react";
import { forwardRef, useEffect, useRef, useState } from "react";
import { api, type Correction, type CorrectionRequest, type JobDetail, type Language } from "../api/client";
import { verdictLabel, verdictStyle } from "../lib/verdicts";
import { useStore } from "../state/store";
import { Dialog, Logo, Spinner } from "./ui";

const RELATIONSHIPS = [["elder", "Parent / elder"], ["friend", "Friend"], ["colleague", "Colleague"], ["group_admin", "Group admin"], ["other", "Other"]] as const;
const TONES = ["gentle", "respectful", "neutral", "direct", "formal"] as const;

export default function CorrectionDialog() {
  const s = useStore();
  const jobId = s.correctionJobId;
  const detail = jobId ? s.jobs[jobId]?.detail : undefined;
  const [form, setForm] = useState<CorrectionRequest>({ relationship: "elder", channel: "private", language: (s.prefs.language ?? "en") as Language, tone: "respectful" });
  const [result, setResult] = useState<Correction | null>(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const card = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setResult(null);
    setText("");
  }, [jobId]);

  if (!jobId || !detail) return null;
  const close = () => s.set({ correctionJobId: null });

  const generate = async () => {
    setBusy(true);
    try {
      const c = await api.createCorrection(jobId, form);
      setResult(c);
      const links = c.links.map((l) => `${l.publisher}: ${l.url}`).join("\n");
      setText(links ? `${c.text}\n\nSources:\n${links}` : c.text);
    } catch (e) {
      s.toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      s.toast("Copy failed - select the text and copy it manually.", "error");
    }
  };

  const share = async () => {
    if (navigator.share) {
      await navigator.share({ text }).catch(() => {});
    } else {
      s.toast("Sharing isn't supported in this browser - use Copy instead.", "info");
    }
  };

  const download = async () => {
    if (!card.current) return;
    try {
      const url = await toPng(card.current, { pixelRatio: 2, cacheBust: true });
      const a = document.createElement("a");
      a.href = url;
      a.download = `satyasetu-evidence-card-${jobId.slice(0, 8)}.png`;
      a.click();
    } catch {
      s.toast("Could not create the image.", "error");
    }
  };

  return (
    <Dialog open onClose={close} title={s.t("correct")} wide>
      <div className="grid gap-6 p-5 md:grid-cols-[1fr_300px]">
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <Field label="Sending to">
              <select value={form.relationship} onChange={(e) => setForm({ ...form, relationship: e.target.value as any })} className="select">
                {RELATIONSHIPS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </Field>
            <Field label="Where">
              <select value={form.channel} onChange={(e) => setForm({ ...form, channel: e.target.value as any })} className="select">
                <option value="private">Private chat</option>
                <option value="group">Group</option>
              </select>
            </Field>
            <Field label={s.t("language")}>
              <select value={form.language} onChange={(e) => setForm({ ...form, language: e.target.value as any })} className="select">
                <option value="en">English</option><option value="hi">हिन्दी</option><option value="mr">मराठी</option>
              </select>
            </Field>
            <Field label="Tone">
              <select value={form.tone} onChange={(e) => setForm({ ...form, tone: e.target.value as any })} className="select capitalize">
                {TONES.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </Field>
          </div>
          <button onClick={() => void generate()} disabled={busy}
                  className="focus-ring inline-flex h-10 items-center gap-2 rounded-full bg-brand px-4 text-sm font-semibold text-brand-ink hover:brightness-110 disabled:opacity-60">
            {busy ? <Spinner /> : <Sparkles size={16} />} {result ? s.t("regenerate") : s.t("generate")}
          </button>

          {result && (
            <div className="animate-fade-up">
              <label className="text-xs font-semibold text-ink-2" htmlFor="corr-text">Your message (editable)</label>
              <textarea id="corr-text" value={text} onChange={(e) => setText(e.target.value)} rows={8}
                        className="mt-1 w-full rounded-xl border border-line bg-surface p-3 text-[14.5px] leading-relaxed focus:outline-none focus:ring-2 focus:ring-brand/30" />
              <p className="mt-1 text-[11px] text-ink-3">
                {result.generator === "template"
                  ? "Written from a template using only the verified findings."
                  : `Drafted by ${result.generator.replace("model:", "")} and checked: verdict matches, no numbers or links beyond the evidence${result.validation.rejected_drafts ? ` (${result.validation.rejected_drafts} draft rejected)` : ""}.`}
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                <ActionBtn onClick={copy} icon={copied ? <Check size={15} /> : <Copy size={15} />}>{copied ? s.t("copied") : s.t("copy")}</ActionBtn>
                <ActionBtn onClick={share} icon={<Share2 size={15} />}>{s.t("share")}</ActionBtn>
              </div>
            </div>
          )}
        </div>

        <div>
          <p className="mb-2 text-xs font-semibold text-ink-2">Evidence card</p>
          <EvidenceCard ref={card} d={detail} lang={(form.language ?? "en") as Language} />
          <button onClick={() => void download()}
                  className="focus-ring mt-3 inline-flex h-9 w-full items-center justify-center gap-2 rounded-full border border-line text-sm font-semibold hover:bg-sunken">
            <Download size={15} /> {s.t("downloadCard")}
          </button>
        </div>
      </div>
      <style>{`.select{height:2.5rem;width:100%;border-radius:.75rem;border:1px solid rgb(var(--line));background:rgb(var(--surface));padding:0 .6rem;font-size:.875rem}`}</style>
    </Dialog>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-semibold text-ink-2">{label}</span>
      {children}
    </label>
  );
}

function ActionBtn({ onClick, icon, children }: { onClick: () => void; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <button onClick={onClick} className="focus-ring inline-flex h-9 items-center gap-1.5 rounded-full border border-line px-3.5 text-sm font-semibold hover:bg-sunken">
      {icon} {children}
    </button>
  );
}


const EvidenceCard = forwardRef<HTMLDivElement, { d: JobDetail; lang: Language }>(function EvidenceCard({ d, lang }, ref) {
  const st = verdictStyle(d.overall_verdict);
  const claim = d.claims.find((c) => c.checkable) ?? d.claims[0];
  const ex = d.explanation as Record<string, any> | null;
  const cited = d.sources.filter((x) => x.label).slice(0, 3);
  return (
    <div ref={ref} className="overflow-hidden rounded-2xl border border-line bg-white text-slate-900" style={{ width: 300 }}>
      <div className={clsx("h-2", st.bar)} />
      <div className="p-4">
        <div className="flex items-center gap-2">
          <Logo size={22} />
          <span className="text-[13px] font-bold">SatyaSetu</span>
          <span className="ml-auto text-[10px] text-slate-500">{d.finished_at ? new Date(d.finished_at).toLocaleDateString() : ""}</span>
        </div>
        {claim && <p className="mt-3 text-[13px] font-medium leading-snug">“{claim.original_text.slice(0, 180)}”</p>}
        <p className="mt-3 text-[11px] font-semibold uppercase tracking-wide text-slate-500">Finding</p>
        <p className="text-lg font-bold">{verdictLabel(d.overall_verdict, lang)}</p>
        {ex?.summary && <p className="mt-1 text-[12px] leading-snug text-slate-700">{String(ex.summary).slice(0, 260)}</p>}
        {cited.length > 0 && (
          <div className="mt-3 border-t border-slate-200 pt-2">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">Sources</p>
            {cited.map((x) => <p key={x.id} className="truncate text-[11px] text-slate-700">[{x.label}] {x.publisher || x.domain}</p>)}
          </div>
        )}
        <p className="mt-3 rounded-md bg-slate-100 px-2 py-1.5 text-[9.5px] leading-snug text-slate-600">
          Independent automated fact-check summary. Not an official government or institutional notice.
        </p>
      </div>
    </div>
  );
});
