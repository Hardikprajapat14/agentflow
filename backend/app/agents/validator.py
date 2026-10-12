"""Validator agent: deterministic checks on tool outputs + LLM grounding check on the final report."""
import logging

from app.models import WorkflowStep
from app.services.llm import LLMClient, LLMError
from app.utils.serialization import compact_json

logger = logging.getLogger(__name__)
CRITICAL_TOOLS = {"analyze_data", "ml_analysis", "read_document", "create_chart", "send_email"}


def validate_workflow(steps: list[WorkflowStep]) -> dict:
    checks, warnings = [], []
    for s in steps:
        if s.step_type != "tool":
            continue
        out = s.output_data or {}
        data = out.get("data") or {}
        if s.status == "failed":
            ok, msg = False, f"Step failed: {s.error}"
        elif s.status != "completed":
            ok, msg = False, f"Step did not run (status: {s.status})"
        elif not out.get("summary"):
            ok, msg = False, "Empty output"
        elif s.tool_name == "analyze_data" and not data.get("totals_by_period"):
            ok, msg = False, "No aggregated results were produced"
        elif s.tool_name == "ml_analysis" and "anomalies" not in data:
            ok, msg = False, "ML output missing anomaly results"
        elif s.tool_name == "rag_search" and not data.get("passages"):
            ok, msg = True, "No relevant passages retrieved (report will note missing policy context)"
            warnings.append(f"Step {s.step_number}: {msg}")
        elif s.tool_name == "web_search" and not data.get("results"):
            ok, msg = True, "No web results"
            warnings.append(f"Step {s.step_number}: {msg}")
        else:
            ok, msg = True, "Output present and structurally valid"
        critical = s.tool_name in CRITICAL_TOOLS
        if not ok and not critical:
            warnings.append(f"Step {s.step_number} ({s.tool_name}): {msg}")
        checks.append({"step": s.step_number, "tool": s.tool_name, "passed": ok, "critical": critical, "message": msg})
    passed = all(c["passed"] for c in checks if c["critical"])
    return {"passed": passed, "checks": checks, "warnings": warnings,
            "completed_tool_steps": sum(1 for c in checks if c["passed"])}


GROUNDING_SYSTEM = """You are a strict fact-checker. Compare the REPORT against the EVIDENCE collected by tools.
Respond with ONE JSON object: {"grounded": true|false, "score": 0-100, "unsupported_claims": ["..."]}.
Flag any number, name, date or conclusion in the report that is not supported by the evidence. Ignore style."""


def check_grounding(llm: LLMClient, report_md: str, evidence: str) -> dict:
    try:
        res = llm.json([{"role": "system", "content": GROUNDING_SYSTEM},
                        {"role": "user", "content": f"EVIDENCE:\n{evidence}\n\nREPORT:\n{report_md[:6000]}"}], max_tokens=600)
        score = int(res.get("score", 0))
        claims = [str(c) for c in (res.get("unsupported_claims") or [])][:8]
        return {"grounded": bool(res.get("grounded", score >= 70)) and score >= 60, "score": score,
                "unsupported_claims": claims, "method": "llm"}
    except (LLMError, ValueError, TypeError) as exc:
        logger.warning("Grounding check unavailable: %s", exc)
        return {"grounded": None, "score": None, "unsupported_claims": [], "method": "skipped",
                "note": f"LLM grounding check unavailable: {str(exc)[:160]}"}


def build_evidence(steps: list[WorkflowStep], max_chars: int = 7000) -> str:
    parts = []
    for s in steps:
        if s.step_type == "tool" and s.status == "completed" and s.output_data:
            data = compact_json({k: v for k, v in (s.output_data.get("data") or {}).items()
                                 if k not in ("sample", "passages", "numeric_summary")}, 1200)
            parts.append(f"[Step {s.step_number} | {s.tool_name}]\n{s.output_data.get('summary', '')}\nDATA: {data}")
    text = "\n\n".join(parts)
    return text if len(text) <= max_chars else text[:max_chars] + "\n...[truncated]"
