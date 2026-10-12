import { AlertCircle, CheckCircle2, ChevronDown, ChevronRight, Circle, Loader2, PauseCircle, SkipForward, XCircle } from "lucide-react";
import { useState } from "react";
import type { Step } from "../types";
import { fmtDuration, fmtTime } from "../utils/format";
import StatusBadge from "./StatusBadge";

const ICON: Record<string, JSX.Element> = {
  completed: <CheckCircle2 className="h-6 w-6 text-emerald-500" />,
  running: <Loader2 className="h-6 w-6 animate-spin text-sky-500" />,
  failed: <XCircle className="h-6 w-6 text-rose-500" />,
  rejected: <XCircle className="h-6 w-6 text-rose-500" />,
  awaiting_approval: <PauseCircle className="h-6 w-6 text-amber-500" />,
  skipped: <SkipForward className="h-6 w-6 text-slate-400" />,
  pending: <Circle className="h-6 w-6 text-slate-300" />,
};
const TOOL_LABEL: Record<string, string> = {
  planner: "AI Planning", analyze_data: "Data Analysis", ml_analysis: "ML Analysis", rag_search: "RAG Retrieval",
  web_search: "Web Search", create_chart: "Visualization", read_document: "Data Extraction", send_email: "Email (sensitive)",
  validator: "Validation", report_generator: "Report Generation",
};

function Json({ label, value }: { label: string; value: unknown }) {
  if (value == null) return null;
  return (
    <div>
      <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <pre className="max-h-64 overflow-auto rounded-lg bg-slate-900 p-3 text-xs text-slate-100">{JSON.stringify(value, null, 2)}</pre>
    </div>
  );
}

export default function StepTimeline({ steps }: { steps: Step[] }) {
  const [open, setOpen] = useState<Record<number, boolean>>({});
  return (
    <ol className="relative">
      {steps.map((s, i) => {
        const expanded = open[s.id] ?? (s.status === "failed");
        const summary = s.output_data?.summary as string | undefined;
        return (
          <li key={s.id} className="relative flex gap-4 pb-6 last:pb-0">
            {i < steps.length - 1 && <span className="absolute left-3 top-7 h-full w-px bg-slate-200" />}
            <div className="z-10 bg-slate-50">{ICON[s.status] ?? ICON.pending}</div>
            <div className="card min-w-0 flex-1 p-4">
              <button className="flex w-full items-start justify-between gap-3 text-left" onClick={() => setOpen({ ...open, [s.id]: !expanded })}>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold">{s.step_number}. {s.name}</span>
                    <StatusBadge status={s.status} />
                    {s.tool_name && <span className="rounded bg-indigo-50 px-2 py-0.5 text-xs text-indigo-700">{TOOL_LABEL[s.tool_name] ?? s.tool_name}</span>}
                  </div>
                  <div className="mt-1 text-xs text-slate-500">
                    started {fmtTime(s.started_at)} - finished {fmtTime(s.completed_at)} - duration {fmtDuration(s.duration)}
                  </div>
                  {summary && !expanded && <p className="mt-2 line-clamp-2 whitespace-pre-line text-sm text-slate-600">{summary}</p>}
                </div>
                {expanded ? <ChevronDown className="h-4 w-4 shrink-0" /> : <ChevronRight className="h-4 w-4 shrink-0" />}
              </button>
              {s.error && (
                <div className="mt-3 flex gap-2 rounded-lg bg-rose-50 p-3 text-sm text-rose-800"><AlertCircle className="h-4 w-4 shrink-0" />{s.error}</div>
              )}
              {expanded && (
                <div className="mt-3 space-y-3">
                  {summary && <p className="whitespace-pre-line text-sm text-slate-700">{summary}</p>}
                  <Json label="Input" value={s.input_data} />
                  <Json label="Output data" value={s.output_data?.data} />
                </div>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
