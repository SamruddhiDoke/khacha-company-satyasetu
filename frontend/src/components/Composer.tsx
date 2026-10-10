import clsx from "clsx";
import { FileText, Image as ImageIcon, Mic, Music, Paperclip, SendHorizontal, Square, Video, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useStore } from "../state/store";
import { IconButton, Spinner } from "./ui";

const MAX_CHARS = 6000;

export default function Composer() {
  const s = useStore();
  const [file, setFile] = useState<File | null>(null);
  const [menu, setMenu] = useState(false);
  const [recording, setRecording] = useState<MediaRecorder | null>(null);
  const [recSecs, setRecSecs] = useState(0);
  const ta = useRef<HTMLTextAreaElement>(null);
  const picker = useRef<HTMLInputElement>(null);
  const text = s.draft;

  useEffect(() => {
    const el = ta.current;
    if (!el) return;
    el.style.height = "0px";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [text]);

  useEffect(() => {
    if (text && ta.current && document.activeElement !== ta.current) ta.current.focus();
  }, [text]);

  useEffect(() => {
    if (!recording) return;
    const t = setInterval(() => setRecSecs((x) => x + 1), 1000);
    return () => clearInterval(t);
  }, [recording]);

  const canSend = !s.sending && (file !== null || (text.trim().length > 0 && text.length <= MAX_CHARS));

  const submit = async () => {
    if (!canSend) return;
    const ok = file ? await s.upload(file, text) : await s.send(text);
    if (ok) {
      s.set({ draft: "" });
      setFile(null);
    }
  };

  const choose = (accept: string) => {
    setMenu(false);
    if (picker.current) {
      picker.current.accept = accept;
      picker.current.click();
    }
  };

  const record = async () => {
    setMenu(false);
    if (!navigator.mediaDevices?.getUserMedia) {
      s.toast("Voice recording is not available in this browser.", "error");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const rec = new MediaRecorder(stream);
      const chunks: Blob[] = [];
      rec.ondataavailable = (e) => chunks.push(e.data);
      rec.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(chunks, { type: rec.mimeType || "audio/webm" });
        setFile(new File([blob], `voice-note-${Date.now()}.webm`, { type: blob.type }));
        setRecording(null);
      };
      rec.start();
      setRecSecs(0);
      setRecording(rec);
    } catch {
      s.toast("Microphone permission was denied.", "error");
    }
  };

  const modal = s.caps?.modalities;

  return (
    <div className="shrink-0 border-t border-line bg-surface-2 px-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-3 md:px-5">
      <div className="mx-auto max-w-3xl">
        {file && (
          <div className="mb-2 flex items-center gap-3 rounded-xl border border-line bg-surface px-3 py-2 animate-fade-up">
            <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-soft text-brand">
              {file.type.startsWith("image") ? <ImageIcon size={18} /> : file.type.includes("pdf") ? <FileText size={18} /> : <Music size={18} />}
            </span>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">{file.name}</p>
              <p className="text-xs text-ink-3">{(file.size / 1024).toFixed(0)} KB · text will be extracted on send{text ? " · caption added" : ""}</p>
            </div>
            <IconButton label="Remove attachment" onClick={() => setFile(null)} className="h-8 w-8">
              <X size={16} />
            </IconButton>
          </div>
        )}

        <div className="relative flex items-end gap-2">
          <div className="relative">
            <IconButton label={s.t("attach")} onClick={() => setMenu((m) => !m)} aria-expanded={menu} aria-haspopup="menu" disabled={!!recording}>
              <Paperclip size={20} />
            </IconButton>
            {menu && (
              <>
                <div className="fixed inset-0 z-10" onClick={() => setMenu(false)} />
                <div role="menu" className="absolute bottom-12 left-0 z-20 w-64 overflow-hidden rounded-2xl border border-line bg-surface py-1.5 shadow-pop animate-fade-up">
                  <MenuItem icon={<ImageIcon size={18} />} label="Image or screenshot" hint="Text is read with OCR"
                            disabled={modal ? !modal.image?.configured : false} onClick={() => choose("image/png,image/jpeg,image/webp")} />
                  <MenuItem icon={<FileText size={18} />} label="PDF / circular" hint="Includes document checks"
                            onClick={() => choose("application/pdf")} />
                  <MenuItem icon={<Music size={18} />} label="Audio file" hint="Transcribed locally"
                            disabled={modal ? !modal.audio?.configured : false} onClick={() => choose("audio/*")} />
                  <MenuItem icon={<Mic size={18} />} label="Record voice note" hint="Transcribed locally"
                            disabled={modal ? !modal.audio?.configured : false} onClick={() => void record()} />
                  <MenuItem icon={<Video size={18} />} label="Video" hint="Not supported yet" disabled onClick={() => {}} />
                </div>
              </>
            )}
            <input
              ref={picker}
              type="file"
              hidden
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) setFile(f);
                e.target.value = "";
              }}
            />
          </div>

          {recording ? (
            <div className="flex min-h-[44px] flex-1 items-center gap-3 rounded-2xl border border-danger/30 bg-danger-soft px-4 text-sm text-danger">
              <span className="h-2.5 w-2.5 animate-pulse rounded-full bg-danger" />
              Recording… {Math.floor(recSecs / 60)}:{String(recSecs % 60).padStart(2, "0")}
              <button onClick={() => recording.stop()} className="focus-ring ml-auto flex items-center gap-1.5 rounded-lg px-2 py-1 font-semibold">
                <Square size={14} /> Stop
              </button>
            </div>
          ) : (
            <div className="flex min-h-[44px] flex-1 items-end rounded-2xl border border-line bg-surface px-4 py-2.5 focus-within:border-brand/50 focus-within:ring-2 focus-within:ring-brand/15">
              <textarea
                ref={ta}
                value={text}
                rows={1}
                maxLength={MAX_CHARS + 500}
                onChange={(e) => s.set({ draft: e.target.value })}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                    e.preventDefault();
                    void submit();
                  }
                }}
                placeholder={file ? "Add a caption (optional)…" : s.t("composerPlaceholder")}
                aria-label="Message"
                className="max-h-[200px] w-full resize-none bg-transparent text-[15px] leading-6 placeholder:text-ink-3 focus:outline-none"
              />
            </div>
          )}

          <button
            type="button"
            onClick={() => void submit()}
            disabled={!canSend}
            aria-label={s.t("send")}
            title={s.t("send")}
            className={clsx(
              "focus-ring flex h-11 w-11 shrink-0 items-center justify-center rounded-full transition-all",
              canSend ? "bg-brand text-brand-ink shadow-md hover:brightness-110 active:scale-95" : "bg-sunken text-ink-3",
            )}
          >
            {s.sending ? <Spinner className="h-4 w-4" /> : <SendHorizontal size={19} />}
          </button>
        </div>
        <div className="mt-1.5 flex justify-between px-1 text-[11px] text-ink-3">
          <span className="hidden sm:inline">Enter to send · Shift+Enter for a new line</span>
          {text.length > MAX_CHARS * 0.8 && (
            <span className={clsx(text.length > MAX_CHARS && "font-semibold text-danger")}>
              {text.length}/{MAX_CHARS}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

function MenuItem({ icon, label, hint, onClick, disabled }:
  { icon: React.ReactNode; label: string; hint: string; onClick: () => void; disabled?: boolean }) {
  return (
    <button
      role="menuitem"
      disabled={disabled}
      onClick={onClick}
      className="flex w-full items-center gap-3 px-3.5 py-2 text-left hover:bg-sunken disabled:cursor-not-allowed disabled:opacity-45 disabled:hover:bg-transparent"
    >
      <span className="text-brand">{icon}</span>
      <span>
        <span className="block text-sm font-medium">{label}</span>
        <span className="block text-xs text-ink-3">{hint}</span>
      </span>
    </button>
  );
}
