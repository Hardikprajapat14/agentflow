import { ShieldAlert } from "lucide-react";
import { useState } from "react";
import { api, errorMessage } from "../services/api";
import type { Approval } from "../types";

export default function ApprovalCard({ approval, onDone }: { approval: Approval; onDone: () => void }) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const resolve = async (approve: boolean) => {
    setBusy(true); setErr("");
    try { await api.resolveApproval(approval.id, approve, note || undefined); onDone(); }
    catch (e) { setErr(errorMessage(e)); }
    finally { setBusy(false); }
  };
  return (
    <div className="rounded-xl border-2 border-amber-300 bg-amber-50 p-4">
      <div className="flex items-center gap-2 font-semibold text-amber-900"><ShieldAlert className="h-5 w-5" /> Human approval required</div>
      <p className="mt-1 text-sm font-medium">{approval.action}</p>
      <p className="mt-1 text-sm text-amber-900/80">{approval.reason}</p>
      <input className="input mt-3" placeholder="Optional note" value={note} onChange={(e) => setNote(e.target.value)} />
      {err && <p className="mt-2 text-sm text-rose-700">{err}</p>}
      <div className="mt-3 flex gap-2">
        <button className="btn-primary" disabled={busy} onClick={() => resolve(true)}>Approve &amp; continue</button>
        <button className="btn-danger" disabled={busy} onClick={() => resolve(false)}>Reject</button>
      </div>
    </div>
  );
}
