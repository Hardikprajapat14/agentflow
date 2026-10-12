import { Rocket } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { usePolling } from "../hooks/usePolling";
import { api, errorMessage } from "../services/api";

const EXAMPLES = [
  "Analyze the sales data, identify unusual regional drops, compare the findings with the company sales policy, create visualizations, and generate an executive report.",
  "Which regions are underperforming in the latest month? Detect anomalies with ML, forecast next month and recommend actions per our sales policy.",
  "Summarize customer lifetime value by segment and region, chart it, and highlight churn risk.",
];

export default function NewWorkflow() {
  const nav = useNavigate();
  const docs = usePolling(api.documents, 5000);
  const [text, setText] = useState(EXAMPLES[0]);
  const [approval, setApproval] = useState(true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const ready = (docs.data ?? []).filter((d) => d.status === "ready");

  const submit = async () => {
    setBusy(true); setErr("");
    try { const wf = await api.createWorkflow(text, approval); nav(`/workflows/${wf.id}`); }
    catch (e) { setErr(errorMessage(e)); setBusy(false); }
  };
  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <h1 className="text-2xl font-bold">New workflow</h1>
      <div className="card space-y-4 p-5">
        <label className="block text-sm font-medium">Describe the business task</label>
        <textarea className="input h-36" value={text} onChange={(e) => setText(e.target.value)} maxLength={4000} />
        <div className="flex flex-wrap gap-2">
          {EXAMPLES.map((ex, i) => <button key={i} className="rounded-full border border-slate-300 px-3 py-1 text-xs hover:bg-slate-50" onClick={() => setText(ex)}>Example {i + 1}</button>)}
        </div>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={approval} onChange={(e) => setApproval(e.target.checked)} /> Require human approval before the final report is generated</label>
        {ready.length === 0 && (
          <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-800">You have no processed documents yet. <Link className="underline" to="/documents">Upload a dataset or policy</Link> so the agents have something to work with.</p>
        )}
        {ready.length > 0 && <p className="text-xs text-slate-500">Available: {ready.map((d) => d.filename).join(", ")}</p>}
        {err && <p className="rounded-lg bg-rose-50 p-3 text-sm text-rose-700">{err}</p>}
        <button className="btn-primary" disabled={busy || text.trim().length < 10} onClick={submit}><Rocket className="h-4 w-4" /> {busy ? "Starting..." : "Run workflow"}</button>
      </div>
    </div>
  );
}
