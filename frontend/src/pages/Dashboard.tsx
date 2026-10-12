import { CheckCircle2, Clock, ListChecks, ShieldAlert } from "lucide-react";
import { Link } from "react-router-dom";
import ApprovalCard from "../components/ApprovalCard";
import StatusBadge from "../components/StatusBadge";
import { usePolling } from "../hooks/usePolling";
import { api } from "../services/api";
import { fmtDate } from "../utils/format";

export default function Dashboard() {
  const wfs = usePolling(api.workflows, 3000);
  const approvals = usePolling(() => api.approvals("pending"), 3000);
  const list = wfs.data ?? [];
  const stats = [
    { label: "Total workflows", value: list.length, icon: ListChecks, color: "text-indigo-600" },
    { label: "Completed", value: list.filter((w) => w.status === "completed").length, icon: CheckCircle2, color: "text-emerald-600" },
    { label: "In progress", value: list.filter((w) => ["pending", "planning", "running"].includes(w.status)).length, icon: Clock, color: "text-sky-600" },
    { label: "Awaiting approval", value: list.filter((w) => w.status === "awaiting_approval").length, icon: ShieldAlert, color: "text-amber-600" },
  ];
  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Dashboard</h1>
        <Link to="/new" className="btn-primary">New workflow</Link>
      </div>
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {stats.map(({ label, value, icon: Icon, color }) => (
          <div key={label} className="card flex items-center gap-3 p-4">
            <Icon className={`h-8 w-8 ${color}`} />
            <div><div className="text-2xl font-bold">{value}</div><div className="text-xs text-slate-500">{label}</div></div>
          </div>
        ))}
      </div>
      {(approvals.data ?? []).length > 0 && (
        <section className="space-y-3">
          <h2 className="font-semibold">Pending approvals</h2>
          {approvals.data!.map((a) => (
            <div key={a.id}>
              <Link to={`/workflows/${a.workflow_id}`} className="mb-1 block text-sm text-indigo-600 hover:underline">{a.workflow_title}</Link>
              <ApprovalCard approval={a} onDone={() => { approvals.refresh(); wfs.refresh(); }} />
            </div>
          ))}
        </section>
      )}
      <section>
        <h2 className="mb-3 font-semibold">Recent workflows</h2>
        {wfs.error && <p className="rounded-lg bg-rose-50 p-3 text-sm text-rose-700">{wfs.error}</p>}
        {!wfs.loading && list.length === 0 && (
          <div className="card p-8 text-center text-slate-500">No workflows yet. <Link className="text-indigo-600" to="/new">Create your first one</Link>.</div>
        )}
        <div className="space-y-3">
          {list.map((w) => (
            <Link key={w.id} to={`/workflows/${w.id}`} className="card block p-4 transition hover:border-indigo-300">
              <div className="flex items-center justify-between gap-3">
                <div className="min-w-0"><div className="truncate font-semibold">{w.title}</div><div className="truncate text-sm text-slate-500">{w.description}</div></div>
                <StatusBadge status={w.status} />
              </div>
              <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-slate-100">
                <div className="h-full bg-indigo-500 transition-all" style={{ width: `${w.total_steps ? (w.completed_steps / w.total_steps) * 100 : 0}%` }} />
              </div>
              <div className="mt-2 text-xs text-slate-500">{w.completed_steps}/{w.total_steps} steps - {fmtDate(w.created_at)}</div>
            </Link>
          ))}
        </div>
      </section>
    </div>
  );
}
