import type { Language } from "../api/client";

export type VerdictKey =
  | "verified" | "false" | "partly_true" | "misleading" | "outdated" | "conflicting"
  | "insufficient_evidence" | "not_checkable" | "mixed";

// Mirrors backend app/pipeline/explain.py VERDICT_LABELS.
const LABELS: Record<Language, Record<VerdictKey, string>> = {
  en: { verified: "Verified", false: "False", partly_true: "Partly true", misleading: "Misleading", outdated: "Outdated",
        conflicting: "Conflicting evidence", insufficient_evidence: "Insufficient evidence", not_checkable: "Not checkable",
        mixed: "Mixed findings" },
  hi: { verified: "पुष्ट", false: "गलत", partly_true: "आंशिक रूप से सही", misleading: "भ्रामक", outdated: "पुरानी जानकारी",
        conflicting: "विरोधाभासी साक्ष्य", insufficient_evidence: "अपर्याप्त साक्ष्य", not_checkable: "जाँच योग्य नहीं",
        mixed: "मिले-जुले निष्कर्ष" },
  mr: { verified: "पुष्टी झाली", false: "खोटे", partly_true: "अंशतः खरे", misleading: "दिशाभूल करणारे", outdated: "जुनी माहिती",
        conflicting: "परस्परविरोधी पुरावे", insufficient_evidence: "अपुरे पुरावे", not_checkable: "तपासता येत नाही",
        mixed: "संमिश्र निष्कर्ष" },
};

export const VERDICT_HINT: Record<VerdictKey, string> = {
  verified: "Credible sources support this.",
  false: "Credible sources contradict this.",
  partly_true: "Only part of this is supported.",
  misleading: "Supported in part, but leaves out context that changes its meaning.",
  outdated: "This was true earlier but has since changed.",
  conflicting: "Credible sources disagree.",
  insufficient_evidence: "Not enough credible evidence was found either way. This is not the same as false.",
  not_checkable: "Opinion, prediction or other statement that can't be fact-checked.",
  mixed: "Different claims in this message reached different findings.",
};

// Tailwind classes per verdict: chip background/text and accent dot.
export const VERDICT_STYLE: Record<VerdictKey, { chip: string; dot: string; bar: string }> = {
  verified: { chip: "bg-emerald-50 text-emerald-800 ring-emerald-600/20 dark:bg-emerald-500/10 dark:text-emerald-300", dot: "bg-emerald-500", bar: "bg-emerald-500" },
  false: { chip: "bg-rose-50 text-rose-800 ring-rose-600/20 dark:bg-rose-500/10 dark:text-rose-300", dot: "bg-rose-500", bar: "bg-rose-500" },
  partly_true: { chip: "bg-orange-50 text-orange-800 ring-orange-600/20 dark:bg-orange-500/10 dark:text-orange-300", dot: "bg-orange-500", bar: "bg-orange-500" },
  misleading: { chip: "bg-amber-50 text-amber-800 ring-amber-600/25 dark:bg-amber-500/10 dark:text-amber-300", dot: "bg-amber-500", bar: "bg-amber-500" },
  outdated: { chip: "bg-indigo-50 text-indigo-800 ring-indigo-600/20 dark:bg-indigo-500/10 dark:text-indigo-300", dot: "bg-indigo-500", bar: "bg-indigo-500" },
  conflicting: { chip: "bg-violet-50 text-violet-800 ring-violet-600/20 dark:bg-violet-500/10 dark:text-violet-300", dot: "bg-violet-500", bar: "bg-violet-500" },
  insufficient_evidence: { chip: "bg-slate-100 text-slate-700 ring-slate-500/20 dark:bg-slate-500/15 dark:text-slate-300", dot: "bg-slate-400", bar: "bg-slate-400" },
  not_checkable: { chip: "bg-slate-50 text-slate-600 ring-slate-400/20 dark:bg-slate-500/10 dark:text-slate-400", dot: "bg-slate-300", bar: "bg-slate-300" },
  mixed: { chip: "bg-fuchsia-50 text-fuchsia-800 ring-fuchsia-600/20 dark:bg-fuchsia-500/10 dark:text-fuchsia-300", dot: "bg-fuchsia-500", bar: "bg-fuchsia-500" },
};

export function verdictLabel(v: string | null | undefined, lang: Language): string {
  if (!v) return "";
  return LABELS[lang]?.[v as VerdictKey] ?? LABELS.en[v as VerdictKey] ?? v;
}

export function verdictStyle(v: string | null | undefined) {
  return VERDICT_STYLE[(v as VerdictKey) ?? "insufficient_evidence"] ?? VERDICT_STYLE.insufficient_evidence;
}

export const STRENGTH_LABEL: Record<string, string> = {
  none: "None", weak: "Weak", moderate: "Moderate", strong: "Strong",
};

export const STAGES: { key: string; label: string }[] = [
  { key: "received", label: "Received" },
  { key: "harm_check", label: "Safety check" },
  { key: "document_checks", label: "Document checks" },
  { key: "extracting_content", label: "Reading linked page" },
  { key: "extracting_claims", label: "Extracting claims" },
  { key: "preparing_queries", label: "Preparing searches" },
  { key: "searching_sources", label: "Searching sources" },
  { key: "fetching_sources", label: "Retrieving pages" },
  { key: "evaluating_evidence", label: "Evaluating evidence" },
  { key: "checking_quotations", label: "Checking quotations" },
  { key: "computing_verdicts", label: "Applying verdict rules" },
  { key: "preparing_explanation", label: "Preparing explanation" },
];

export const ERROR_TEXT: Record<string, string> = {
  provider_not_configured: "Live verification needs API keys. Add GEMINI_API_KEY and TAVILY_API_KEY to .env and restart.",
  quota_exhausted: "The free-tier quota for a provider is used up. Try again after it resets.",
  rate_limited: "A provider rate limit was hit. Wait a minute and retry.",
  timeout: "The check took too long and was stopped.",
  invalid_model_output: "The language model returned an unusable response.",
  content_blocked: "The AI provider refused to process this content.",
  provider_error: "A provider returned an error.",
  interrupted: "The server restarted during this check.",
  internal: "Something went wrong on the server.",
};

export const TIER_LABEL: Record<string, string> = {
  official: "Official", fact_check: "Fact-checker", news: "News", reference: "Reference", other: "Other",
};
