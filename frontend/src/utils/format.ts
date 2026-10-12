export const fmtDate = (s: string | null) => (s ? new Date(s).toLocaleString() : "-");
export const fmtTime = (s: string | null) => (s ? new Date(s).toLocaleTimeString() : "-");
export const fmtDuration = (d: number | null) => (d == null ? "-" : d < 1 ? `${Math.round(d * 1000)} ms` : `${d.toFixed(1)} s`);
export const fmtSize = (b: number) => (b > 1048576 ? `${(b / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1024))} KB`);
export const isActive = (s?: string) => !!s && ["pending", "planning", "running"].includes(s);
