import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import clsx from "clsx";
import { AlertCircle, CheckCircle2, X } from "lucide-react";

type Tone = "success" | "error";
interface Toast {
  id: number;
  tone: Tone;
  message: string;
}

const ToastContext = createContext<(message: string, tone?: Tone) => void>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const dismiss = (id: number) => setToasts((t) => t.filter((x) => x.id !== id));
  const notify = useCallback((message: string, tone: Tone = "success") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, tone, message }]);
    setTimeout(() => dismiss(id), tone === "error" ? 7000 : 3500);
  }, []);

  return (
    <ToastContext.Provider value={notify}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-[360px] max-w-[calc(100vw-32px)] flex-col gap-2" aria-live="polite">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={clsx(
              "pointer-events-auto flex items-start gap-2.5 rounded-lg border bg-surface px-3.5 py-3 text-sm shadow-float",
              t.tone === "error" ? "border-fail/30" : "border-line",
            )}
          >
            {t.tone === "error" ? (
              <AlertCircle className="mt-px h-4 w-4 shrink-0 text-fail" aria-hidden />
            ) : (
              <CheckCircle2 className="mt-px h-4 w-4 shrink-0 text-pass" aria-hidden />
            )}
            <p className="flex-1 text-ink">{t.message}</p>
            <button onClick={() => dismiss(t.id)} className="text-ink-3 hover:text-ink" aria-label="Dismiss">
              <X className="h-4 w-4" />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export const useToast = () => useContext(ToastContext);
