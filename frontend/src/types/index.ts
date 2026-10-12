export interface User { id: number; email: string; name: string }
export type WorkflowStatus = "pending" | "planning" | "running" | "awaiting_approval" | "completed" | "failed" | "rejected";
export type StepStatus = "pending" | "running" | "awaiting_approval" | "completed" | "failed" | "rejected" | "skipped";

export interface Step {
  id: number; step_number: number; name: string; step_type: string; status: StepStatus; tool_name: string | null;
  input_data: Record<string, any> | null; output_data: Record<string, any> | null; error: string | null;
  started_at: string | null; completed_at: string | null; duration: number | null;
}
export interface Approval {
  id: number; workflow_id: number; step_id: number; action: string; reason: string;
  status: "pending" | "approved" | "rejected"; note: string | null; created_at: string; resolved_at: string | null;
  workflow_title?: string | null;
}
export interface ChartSpec {
  title: string; type: "line" | "bar"; series: string[]; data: Record<string, any>[]; x_label: string; y_label: string;
}
export interface WorkflowSummary {
  id: number; title: string; description: string; status: WorkflowStatus; require_approval: boolean;
  error: string | null; created_at: string; started_at: string | null; completed_at: string | null;
  total_steps: number; completed_steps: number;
}
export interface Workflow extends WorkflowSummary {
  plan: Record<string, any> | null;
  result: { report_markdown: string; grounding: Record<string, any>; used_llm: boolean; validation: Record<string, any>; charts: ChartSpec[] } | null;
  steps: Step[]; approvals: Approval[];
}
export interface DocumentItem {
  id: number; filename: string; file_type: string; file_size: number; status: "processing" | "ready" | "failed";
  error: string | null; meta: Record<string, any> | null; created_at: string;
}
export interface AuditEntry { id: number; event_type: string; message: string; created_at: string }
