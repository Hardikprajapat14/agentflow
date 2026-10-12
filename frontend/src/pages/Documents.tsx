import { FileText, Trash2, UploadCloud } from "lucide-react";
import { useRef, useState } from "react";
import StatusBadge from "../components/StatusBadge";
import { usePolling } from "../hooks/usePolling";
import { api, errorMessage } from "../services/api";
import { fmtDate, fmtSize } from "../utils/format";

export default function Documents() {
  const docs = usePolling(api.documents, 2000, (d) => !d || d.some((x) => x.status === "processing") || true);
  const input = useRef<HTMLInputElement>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [drag, setDrag] = useState(false);

  const upload = async (files: FileList | null) => {
    if (!files) return;
    setBusy(true); setErr("");
    for (const f of Array.from(files)) {
      try { await api.upload(f); } catch (e) { setErr(`${f.name}: ${errorMessage(e)}`); }
    }
    setBusy(false); docs.refresh();
  };
  return (
    <div className="mx-auto max-w-4xl space-y-5">
      <h1 className="text-2xl font-bold">Documents</h1>
      <div onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); upload(e.dataTransfer.files); }}
        onClick={() => input.current?.click()}
        className={`card cursor-pointer border-2 border-dashed p-8 text-center ${drag ? "border-indigo-500 bg-indigo-50" : "border-slate-300"}`}>
        <UploadCloud className="mx-auto h-10 w-10 text-indigo-500" />
        <p className="mt-2 font-medium">{busy ? "Uploading..." : "Drop files here or click to upload"}</p>
        <p className="text-xs text-slate-500">CSV, XLSX (datasets) - PDF, DOCX, TXT, MD (knowledge for RAG) - up to 25 MB</p>
        <input ref={input} type="file" multiple hidden accept=".csv,.xlsx,.pdf,.docx,.txt,.md" onChange={(e) => { upload(e.target.files); e.target.value = ""; }} />
      </div>
      {err && <p className="rounded-lg bg-rose-50 p-3 text-sm text-rose-700">{err}</p>}
      <div className="card divide-y divide-slate-100">
        {(docs.data ?? []).length === 0 && <p className="p-6 text-center text-sm text-slate-500">No documents yet.</p>}
        {(docs.data ?? []).map((d) => (
          <div key={d.id} className="flex items-center gap-3 p-4">
            <FileText className="h-6 w-6 shrink-0 text-slate-400" />
            <div className="min-w-0 flex-1">
              <div className="truncate font-medium">{d.filename}</div>
              <div className="text-xs text-slate-500">{d.file_type.toUpperCase()} - {fmtSize(d.file_size)} - {fmtDate(d.created_at)}
                {d.meta?.rows ? ` - ${d.meta.rows} rows` : ""}{d.meta?.chunks ? ` - ${d.meta.chunks} chunks indexed` : ""}</div>
              {d.error && <div className="mt-1 text-xs text-rose-600">{d.error}</div>}
            </div>
            <StatusBadge status={d.status} />
            <button className="text-slate-400 hover:text-rose-600" title="Delete" onClick={async () => { await api.deleteDocument(d.id); docs.refresh(); }}><Trash2 className="h-4 w-4" /></button>
          </div>
        ))}
      </div>
    </div>
  );
}
