import { ArrowLeft, Download, ShieldCheck, Trash2 } from "lucide-react";
import { useState } from "react";
import ReactMarkdown from "react-markdown";
import { Link, useNavigate, useParams } from "react-router-dom";
import remarkGfm from "remark-gfm";
import ApprovalCard from "../components/ApprovalCard";
import ChartCard from "../components/ChartCard";
import StatusBadge from "../components/StatusBadge";
import StepTimeline from "../components/StepTimeline";
import { usePolling } from "../hooks/usePolling";
import { api, errorMessage } from "../services/api";
import { fmtDate, isActive } from "../utils/format";

type Tab = "execution" | "report" | "audit";

export default function WorkflowDetail() {
  const { id = "" } = useParams();
  const nav = useNavigate();
  const [tab, setTab] = useState<Tab>("execution");
  const [err, setErr] = useState("");
  // Real-time monitoring: poll every 1.5s while the workflow is progressing; slower while waiting on a human.
  const wf = usePolling(() => api.workflow(id), 1500, (w) => !w || isActive(w.status) || w.status === "awaiting_approval");
  const audit = usePolling(() => api.audit(id), 4000, () => tab === "audit");
  const w = wf.data;

  if (wf.loading) return <p className="text-slate-500">Loading...</p>;
  if (!w) return <p className="rounded-lg bg-rose-50 p-4 text-rose-700">{wf.error ?? "Workflow not found"} <Link className="underline" to="/">Back</Link></p>;
  const pending = w.approvals.filter((a) => a.status === "pending");
  const g = w.result?.grounding;

  return (
    <div className="mx-auto max-w-5xl space-y-5">
      <Link to="/" className="inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-800"><ArrowLeft className="h-4 w-4" /> Dashboard</Link>
      <div className="card p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0"><h1 className="text-xl font-bold">{w.title}</h1><p className="mt-1 text-sm text-slate-600">{w.description}</p></div>
          <StatusBadge status={w.status} />
        </div>
        <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-xs text-slate-500">
          <span>Created {fmtDate(w.created_at)}</span><span>Completed {fmtDate(w.completed_at)}</span><span>{w.completed_steps}/{w.total_steps} steps</span>
        </div>
        {w.error && <p className="mt-3 rounded-lg bg-rose-50 p-3 text-sm text-rose-800">{w.error}</p>}
        {w.plan?.rationale && <p className="mt-3 rounded-lg bg-indigo-50 p-3 text-sm text-indigo-900"><b>Plan rationale:</b> {w.plan.rationale}</p>}
      </div>
      {pending.map((a) => <ApprovalCard key={a.id} approval={a} onDone={wf.refresh} />)}

      <div className="flex gap-1 border-b border-slate-200">
        {(["execution", "report", "audit"] as Tab[]).map((t) => (
          <button key={t} onClick={() => setTab(t)} className={`px-4 py-2 text-sm font-medium capitalize ${tab === t ? "border-b-2 border-indigo-600 text-indigo-700" : "text-slate-500"}`}>
            {t === "audit" ? "Audit log" : t}
          </button>
        ))}
      </div>

      {tab === "execution" && (w.steps.length ? <StepTimeline steps={w.steps} /> : <p className="text-sm text-slate-500">Waiting for a worker to pick up this workflow...</p>)}

      {tab === "report" && (w.result ? (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <button className="btn-primary" onClick={() => api.downloadReport(w.id, "pdf").catch((e) => setErr(errorMessage(e)))}><Download className="h-4 w-4" /> PDF</button>
            <button className="btn-ghost" onClick={() => api.downloadReport(w.id, "md").catch((e) => setErr(errorMessage(e)))}><Download className="h-4 w-4" /> Markdown</button>
            {g && (
              <span className={`inline-flex items-center gap-1 rounded-full px-3 py-1 text-xs font-medium ${g.grounded === false ? "bg-amber-100 text-amber-800" : "bg-emerald-100 text-emerald-800"}`}>
                <ShieldCheck className="h-3.5 w-3.5" />
                {g.score != null ? `Fact-check score ${g.score}/100` : "Fact-check skipped"}
              </span>
            )}
          </div>
          {err && <p className="text-sm text-rose-700">{err}</p>}
          {(g?.unsupported_claims?.length ?? 0) > 0 && g && <div className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900"><b>Unverified claims flagged:</b><ul className="list-disc pl-5">{g.unsupported_claims.map((c: string, i: number) => <li key={i}>{c}</li>)}</ul></div>}
          <div className="grid gap-4 md:grid-cols-2">{w.result.charts.map((c, i) => <ChartCard key={i} spec={c} />)}</div>
          <article className="card prose-report p-6"><ReactMarkdown remarkPlugins={[remarkGfm]}>{w.result.report_markdown}</ReactMarkdown></article>
        </div>
      ) : <p className="text-sm text-slate-500">The report appears here when the workflow completes.</p>)}

      {tab === "audit" && (
        <div className="card divide-y divide-slate-100">
          {(audit.data ?? []).map((a) => (
            <div key={a.id} className="flex gap-3 p-3 text-sm"><span className="w-40 shrink-0 text-xs text-slate-500">{fmtDate(a.created_at)}</span><span className="w-44 shrink-0 font-mono text-xs text-indigo-700">{a.event_type}</span><span>{a.message}</span></div>
          ))}
        </div>
      )}

      {!isActive(w.status) && (
        <button className="btn-ghost text-rose-600" onClick={async () => { if (confirm("Delete this workflow?")) { await api.deleteWorkflow(w.id); nav("/"); } }}><Trash2 className="h-4 w-4" /> Delete workflow</button>
      )}
    </div>
  );
}
