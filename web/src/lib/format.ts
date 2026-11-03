export function humanize(key: string): string {
  const s = key.replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function fieldLabel(f: { label?: string | null; name?: string; field?: string }): string {
  return f.label || humanize(f.name ?? f.field ?? "");
}

export function toKey(label: string): string {
  return label
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .replace(/^(\d)/, "f_$1")
    .slice(0, 64);
}

export function relativeTime(epochSeconds: number): string {
  const diff = Date.now() / 1000 - epochSeconds;
  if (diff < 45) return "just now";
  if (diff < 3600) return `${Math.round(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)} h ago`;
  const d = new Date(epochSeconds * 1000);
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: diff > 300 * 86400 ? "numeric" : undefined });
}

export function fileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function duration(seconds: number | null | undefined): string {
  if (seconds == null) return "";
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)} s`;
  return `${Math.floor(seconds / 60)} min ${Math.round(seconds % 60)} s`;
}

export const show = (v: unknown): string => (v === null || v === undefined || v === "" ? "—" : String(v));
