import clsx from "clsx";
import { useStore } from "../state/store";

export default function Toasts() {
  const toasts = useStore((s) => s.toasts);
  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-24 z-[60] flex flex-col items-center gap-2 px-4" aria-live="assertive">
      {toasts.map((t) => (
        <div
          key={t.id}
          role={t.tone === "error" ? "alert" : "status"}
          className={clsx(
            "pointer-events-auto max-w-md rounded-xl px-4 py-2.5 text-sm font-medium shadow-pop animate-fade-up",
            t.tone === "error" ? "bg-danger text-white" : t.tone === "success" ? "bg-brand text-brand-ink" : "bg-ink text-surface",
          )}
        >
          {t.text}
        </div>
      ))}
    </div>
  );
}
