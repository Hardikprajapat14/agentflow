import axios from "axios";
import type { Approval, AuditEntry, DocumentItem, User, Workflow, WorkflowSummary } from "../types";

const TOKEN_KEY = "agentflow_token";
export const tokenStore = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (t: string) => localStorage.setItem(TOKEN_KEY, t),
  clear: () => localStorage.removeItem(TOKEN_KEY),
};

// VITE_API_URL is set only when the API lives on another origin (e.g. Render static site + API service).
const API_ORIGIN = ((import.meta.env.VITE_API_URL as string | undefined) ?? "").replace(/\/+$/, "");
export const http = axios.create({ baseURL: `${API_ORIGIN}/api`, timeout: 60000 });
http.interceptors.request.use((cfg) => {
  const t = tokenStore.get();
  if (t) cfg.headers.Authorization = `Bearer ${t}`;
  return cfg;
});
http.interceptors.response.use(
  (r) => r,
  (err) => {
    const isAuthCall = err.config?.url?.startsWith("/auth/login") || err.config?.url?.startsWith("/auth/register");
    if (err.response?.status === 401 && !isAuthCall) {
      tokenStore.clear();
      window.location.href = "/login";
    }
    return Promise.reject(err);
  },
);

export function errorMessage(err: unknown): string {
  const e = err as any;
  const d = e?.response?.data?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((x) => x.msg).join("; ");
  if (e?.code === "ERR_NETWORK") return "Cannot reach the server. Is the backend running?";
  return e?.message ?? "Something went wrong";
}

export const api = {
  login: (email: string, password: string) => http.post<{ access_token: string; user: User }>("/auth/login", { email, password }).then((r) => r.data),
  register: (name: string, email: string, password: string) => http.post<{ access_token: string; user: User }>("/auth/register", { name, email, password }).then((r) => r.data),
  me: () => http.get<User>("/auth/me").then((r) => r.data),
  logout: () => http.post("/auth/logout").catch(() => undefined),
  workflows: () => http.get<WorkflowSummary[]>("/workflows").then((r) => r.data),
  workflow: (id: number | string) => http.get<Workflow>(`/workflows/${id}`).then((r) => r.data),
  createWorkflow: (description: string, require_approval: boolean) => http.post<Workflow>("/workflows", { description, require_approval }).then((r) => r.data),
  deleteWorkflow: (id: number) => http.delete(`/workflows/${id}`),
  audit: (id: number | string) => http.get<AuditEntry[]>(`/workflows/${id}/audit`).then((r) => r.data),
  approvals: (status = "pending") => http.get<Approval[]>("/approvals", { params: { status } }).then((r) => r.data),
  resolveApproval: (id: number, approve: boolean, note?: string) => http.post<Approval>(`/approvals/${id}/resolve`, { approve, note }).then((r) => r.data),
  documents: () => http.get<DocumentItem[]>("/documents").then((r) => r.data),
  upload: (file: File) => { const f = new FormData(); f.append("file", file); return http.post<DocumentItem>("/documents", f).then((r) => r.data); },
  deleteDocument: (id: number) => http.delete(`/documents/${id}`),
  downloadReport: async (id: number, fmt: "pdf" | "md") => {
    const r = await http.get(`/workflows/${id}/report.${fmt}`, { responseType: "blob" });
    const url = URL.createObjectURL(r.data);
    const a = document.createElement("a");
    a.href = url; a.download = `agentflow_report_${id}.${fmt}`; a.click();
    URL.revokeObjectURL(url);
  },
};
