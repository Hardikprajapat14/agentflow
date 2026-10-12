import { Bot } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { api, errorMessage } from "../services/api";

export default function AuthPage({ mode }: { mode: "login" | "register" }) {
  const { user, signIn } = useAuth();
  const nav = useNavigate();
  const [form, setForm] = useState({ name: "", email: "", password: "" });
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  if (user) return <Navigate to="/" replace />;

  const submit = async (e: FormEvent) => {
    e.preventDefault(); setBusy(true); setErr("");
    try {
      const res = mode === "login" ? await api.login(form.email, form.password) : await api.register(form.name, form.email, form.password);
      signIn(res.access_token, res.user); nav("/");
    } catch (e2) { setErr(errorMessage(e2)); } finally { setBusy(false); }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-indigo-50 to-slate-100 p-4">
      <form onSubmit={submit} className="card w-full max-w-sm space-y-4 p-6">
        <div className="flex items-center gap-2 text-xl font-bold text-indigo-700"><Bot className="h-7 w-7" /> AgentFlow</div>
        <p className="text-sm text-slate-500">Autonomous AI workforce &amp; workflow automation</p>
        {mode === "register" && <input className="input" placeholder="Full name" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />}
        <input className="input" type="email" placeholder="Email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
        <input className="input" type="password" placeholder="Password (min 8 characters)" required minLength={8} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
        {err && <p className="rounded-lg bg-rose-50 p-2 text-sm text-rose-700">{err}</p>}
        <button className="btn-primary w-full" disabled={busy}>{busy ? "Please wait..." : mode === "login" ? "Log in" : "Create account"}</button>
        <p className="text-center text-sm text-slate-500">
          {mode === "login" ? <>No account? <Link className="text-indigo-600" to="/register">Register</Link></> : <>Have an account? <Link className="text-indigo-600" to="/login">Log in</Link></>}
        </p>
      </form>
    </div>
  );
}
