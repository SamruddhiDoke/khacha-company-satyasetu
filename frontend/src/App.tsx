import { useEffect } from "react";
import { useStore } from "./state/store";
import Sidebar from "./components/Sidebar";
import ChatPanel from "./components/ChatPanel";
import DetailsPanel from "./components/DetailsPanel";
import CorrectionDialog from "./components/CorrectionDialog";
import SettingsDialog from "./components/SettingsDialog";
import Toasts from "./components/Toasts";

function useTheme() {
  const theme = useStore((s) => s.prefs.theme);
  const lang = useStore((s) => s.prefs.language);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => {
      const dark = theme === "dark" || (theme === "system" && mq.matches);
      document.documentElement.dataset.theme = dark ? "dark" : "light";
    };
    apply();
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, [theme]);
  useEffect(() => {
    document.documentElement.lang = lang ?? "en";
  }, [lang]);
}

export default function App() {
  const init = useStore((s) => s.init);
  const panelJobId = useStore((s) => s.panelJobId);
  useTheme();
  useEffect(() => {
    void init();
  }, [init]);

  return (
    <div className="flex h-[100dvh] w-full overflow-hidden bg-surface">
      <Sidebar />
      <main className="relative flex min-w-0 flex-1">
        <ChatPanel />
        {panelJobId && <DetailsPanel jobId={panelJobId} />}
      </main>
      <CorrectionDialog />
      <SettingsDialog />
      <Toasts />
    </div>
  );
}
