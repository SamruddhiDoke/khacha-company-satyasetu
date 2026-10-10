import clsx from "clsx";
import { CheckCircle2, CircleOff } from "lucide-react";
import { useEffect, useState } from "react";
import { api, type Language, type Usage } from "../api/client";
import { useStore } from "../state/store";
import { Dialog } from "./ui";

export default function SettingsDialog() {
  const s = useStore();
  const [usage, setUsage] = useState<Usage | null>(null);
  useEffect(() => {
    if (s.settingsOpen) {
      void api.usage().then(setUsage).catch(() => setUsage(null));
      void api.capabilities().then((caps) => s.set({ caps })).catch(() => {});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [s.settingsOpen]);
  const caps = s.caps;

  return (
    <Dialog open={s.settingsOpen} onClose={() => s.set({ settingsOpen: false })} title={s.t("settings")}>
      <div className="space-y-6 p-5">
        <section className="grid grid-cols-2 gap-3">
          <label className="block">
            <span className="mb-1 block text-xs font-semibold text-ink-2">{s.t("language")}</span>
            <select value={s.prefs.language} onChange={(e) => void s.setPrefs({ language: e.target.value as Language })}
                    className="h-10 w-full rounded-xl border border-line bg-surface px-2 text-sm">
              <option value="en">English</option><option value="hi">हिन्दी</option><option value="mr">मराठी</option>
            </select>
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-semibold text-ink-2">{s.t("theme")}</span>
            <select value={s.prefs.theme} onChange={(e) => void s.setPrefs({ theme: e.target.value as any })}
                    className="h-10 w-full rounded-xl border border-line bg-surface px-2 text-sm">
              <option value="system">System</option><option value="light">Light</option><option value="dark">Dark</option>
            </select>
          </label>
          <p className="col-span-2 text-xs text-ink-3">Explanations are written in the selected language. Claim matching is tested for English, Hindi and Marathi.</p>
        </section>

        <section>
          <h3 className="mb-2 text-xs font-bold uppercase tracking-wide text-ink-3">{s.t("providers")}</h3>
          {caps ? (
            <ul className="space-y-2">
              {Object.entries(caps.providers).map(([k, p]) => <Row key={k} name={k} ok={p.configured} detail={p.detail} />)}
            </ul>
          ) : <div className="skeleton h-24" />}
          {caps && !caps.live_verification && (
            <div className="mt-3 rounded-xl bg-warn-soft p-3 text-[13px] text-ink">
              <p className="font-semibold text-warn">How to enable live verification</p>
              <ol className="mt-1 list-decimal space-y-0.5 pl-5 text-ink-2">
                <li>Create a free Gemini API key at aistudio.google.com/apikey</li>
                <li>Create a free Tavily key at app.tavily.com</li>
                <li>Put both in the <code>.env</code> file next to docker-compose.yml</li>
                <li>Run <code>docker compose up -d</code> again</li>
              </ol>
            </div>
          )}
        </section>

        <section>
          <h3 className="mb-2 text-xs font-bold uppercase tracking-wide text-ink-3">{s.t("inputs")}</h3>
          {caps && (
            <ul className="space-y-2">
              {Object.entries(caps.modalities).map(([k, p]) => <Row key={k} name={k} ok={p.configured} detail={p.detail} />)}
            </ul>
          )}
        </section>

        <section>
          <h3 className="mb-2 text-xs font-bold uppercase tracking-wide text-ink-3">{s.t("usageToday")}</h3>
          {usage ? (
            <div className="text-[13px] text-ink-2">
              {usage.today.length === 0 && <p>No provider requests today.</p>}
              {usage.today.map((u) => (
                <p key={u.provider}>
                  <span className="font-semibold capitalize text-ink">{u.provider}</span>: {u.requests} request(s)
                  {u.provider === "gemini" ? `, ${u.units.toLocaleString()} tokens` : ""}{u.errors ? `, ${u.errors} error(s)` : ""}
                </p>
              ))}
              <p className="mt-1 text-xs text-ink-3">
                Local limits: Gemini {usage.limits.gemini_requests_per_day}/day · Tavily {usage.limits.tavily_searches_per_day}/day,{" "}
                {usage.limits.tavily_searches_per_month}/month. Requests stop before these limits.
              </p>
            </div>
          ) : <div className="skeleton h-12" />}
        </section>

        {caps && (
          <section className="rounded-xl bg-sunken p-3 text-[12.5px] leading-relaxed text-ink-2">
            <p className="font-semibold text-ink">{s.t("dataNotice")}</p>
            <p className="mt-1">{caps.data_use_notice}</p>
            <p className="mt-1">Conversations, checks and uploads are stored only in your local database and deleted after {caps.retention_days} days of inactivity, or immediately when you delete a chat.</p>
          </section>
        )}
      </div>
    </Dialog>
  );
}

function Row({ name, ok, detail }: { name: string; ok: boolean; detail: string }) {
  return (
    <li className="flex items-start gap-2.5 text-[13px]">
      {ok ? <CheckCircle2 size={16} className="mt-0.5 shrink-0 text-brand" /> : <CircleOff size={16} className="mt-0.5 shrink-0 text-ink-3" />}
      <span>
        <span className={clsx("font-semibold capitalize", !ok && "text-ink-2")}>{name.replace("_", " ")}</span>
        <span className="block text-xs text-ink-3">{detail}</span>
      </span>
    </li>
  );
}
