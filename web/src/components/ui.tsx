import { forwardRef, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";
import clsx from "clsx";
import { Loader2 } from "lucide-react";
import type { QCStatus } from "@/api";

type Variant = "primary" | "secondary" | "ghost" | "danger";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-accent text-white hover:bg-accent-hover border border-accent hover:border-accent-hover",
  secondary: "bg-surface text-ink border border-line-strong hover:bg-panel hover:border-ink-3/50",
  ghost: "text-ink-2 hover:text-ink hover:bg-ink/5 border border-transparent",
  danger: "bg-surface text-fail border border-line-strong hover:bg-fail-weak hover:border-fail/40",
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: "sm" | "md";
  loading?: boolean;
  icon?: ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ variant = "secondary", size = "md", loading, icon, className, children, disabled, ...rest }, ref) => (
    <button
      ref={ref}
      disabled={disabled || loading}
      className={clsx(
        "inline-flex select-none items-center justify-center gap-1.5 whitespace-nowrap rounded font-medium transition-colors duration-150",
        "disabled:cursor-not-allowed disabled:opacity-50",
        size === "md" ? "h-8 px-3 text-sm" : "h-7 px-2.5 text-xs",
        VARIANTS[variant],
        className,
      )}
      {...rest}
    >
      {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : icon}
      {children}
    </button>
  ),
);
Button.displayName = "Button";

const control =
  "w-full rounded border border-line-strong bg-surface px-2.5 text-sm text-ink placeholder:text-ink-3 transition-colors duration-150 hover:border-ink-3/60 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20 disabled:bg-panel disabled:text-ink-3";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(({ className, ...rest }, ref) => (
  <input ref={ref} className={clsx(control, "h-8", className)} {...rest} />
));
Input.displayName = "Input";

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(({ className, ...rest }, ref) => (
  <textarea ref={ref} className={clsx(control, "py-1.5 leading-5", className)} {...rest} />
));
Textarea.displayName = "Textarea";

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(({ className, children, ...rest }, ref) => (
  <select ref={ref} className={clsx(control, "h-8 cursor-pointer pr-7", className)} {...rest}>
    {children}
  </select>
));
Select.displayName = "Select";

export function Label({ children, htmlFor, hint }: { children: ReactNode; htmlFor?: string; hint?: ReactNode }) {
  return (
    <label htmlFor={htmlFor} className="mb-1.5 block">
      <span className="text-sm font-medium text-ink">{children}</span>
      {hint && <span className="mt-0.5 block text-xs text-ink-3">{hint}</span>}
    </label>
  );
}

export function Checkbox({ checked, onChange, label, id }: { checked: boolean; onChange: (v: boolean) => void; label?: string; id?: string }) {
  return (
    <label className="inline-flex cursor-pointer items-center gap-2 text-sm text-ink-2" htmlFor={id}>
      <input
        id={id}
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-4 w-4 cursor-pointer rounded-[4px] border-line-strong accent-[rgb(var(--accent))]"
      />
      {label}
    </label>
  );
}

export const QC_META: Record<QCStatus, { label: string; dot: string; text: string; bg: string }> = {
  PASS: { label: "Verified", dot: "bg-pass", text: "text-pass", bg: "bg-pass-weak" },
  FAIL: { label: "Mismatch", dot: "bg-fail", text: "text-fail", bg: "bg-fail-weak" },
  REVIEW: { label: "Needs review", dot: "bg-review", text: "text-review", bg: "bg-review-weak" },
  ABSENT: { label: "Not in document", dot: "bg-ink-3", text: "text-ink-2", bg: "bg-ink/[0.06]" },
  NOT_CHECKED: { label: "Not checked", dot: "bg-ink-3", text: "text-ink-3", bg: "bg-paper" },
};

export function StatusTag({ status, resolved }: { status: QCStatus; resolved?: boolean }) {
  if (resolved) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-accent-weak px-2 py-0.5 text-xs font-medium text-accent">
        <span className="h-1.5 w-1.5 rounded-full bg-accent" aria-hidden />
        Resolved
      </span>
    );
  }
  const m = QC_META[status];
  return (
    <span className={clsx("inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium", m.bg, m.text)}>
      <span className={clsx("h-1.5 w-1.5 rounded-full", m.dot)} aria-hidden />
      {m.label}
    </span>
  );
}

export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4 border-b border-line px-8 pb-5 pt-7 max-sm:px-4">
      <div className="min-w-0">
        <h1 className="text-xl font-semibold tracking-[-0.01em]">{title}</h1>
        {description && <p className="mt-1 max-w-[70ch] text-sm text-ink-2">{description}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Panel({ children, className }: { children: ReactNode; className?: string }) {
  return <section className={clsx("rounded-lg border border-line bg-surface", className)}>{children}</section>;
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={clsx("h-4 w-4 animate-spin text-ink-3", className)} aria-label="Loading" />;
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx("animate-pulse rounded bg-line/70", className)} />;
}

export function ProgressBar({ value }: { value: number }) {
  return (
    <div className="h-1 w-full overflow-hidden rounded-full bg-line" role="progressbar" aria-valuenow={Math.round(value * 100)} aria-valuemin={0} aria-valuemax={100}>
      <div className="h-full rounded-full bg-accent transition-[width] duration-500 ease-out" style={{ width: `${Math.max(4, value * 100)}%` }} />
    </div>
  );
}
