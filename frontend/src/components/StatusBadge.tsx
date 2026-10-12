const STYLES: Record<string, string> = {
  completed: "bg-emerald-100 text-emerald-800", running: "bg-sky-100 text-sky-800", planning: "bg-sky-100 text-sky-800",
  pending: "bg-slate-100 text-slate-600", awaiting_approval: "bg-amber-100 text-amber-800",
  failed: "bg-rose-100 text-rose-800", rejected: "bg-rose-100 text-rose-800", skipped: "bg-slate-100 text-slate-500",
  ready: "bg-emerald-100 text-emerald-800", processing: "bg-sky-100 text-sky-800",
};
export default function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${STYLES[status] ?? "bg-slate-100"}`}>
      {status.replace("_", " ")}
    </span>
  );
}
