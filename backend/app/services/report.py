"""Final report generation: LLM narrative grounded in tool evidence, verified by the validator, rendered to PDF."""
import logging
import os

from sqlalchemy.orm import Session

from app.agents.validator import build_evidence, check_grounding
from app.config import get_settings
from app.models import Workflow, WorkflowStep
from app.services.llm import LLMClient, LLMError
from app.services.pdf import render_pdf

logger = logging.getLogger(__name__)

REPORT_SYSTEM = """You are a senior business analyst writing an executive report in Markdown.
Use ONLY the EVIDENCE provided; never invent numbers, names or policy rules. Cite step numbers like (Step 3).
If evidence for something requested is missing or a step failed, say so under Limitations.
Structure: # Title, ## Executive Summary (3-5 sentences), ## Key Findings (bullets with numbers), ## Analysis,
## Policy & Compliance (only if policy evidence exists), ## Recommendations (3-5 actionable bullets), ## Limitations.
Be concise: under 700 words."""


def report_paths(workflow_id: int) -> dict:
    base = get_settings().report_dir
    return {"pdf": os.path.join(base, f"workflow_{workflow_id}.pdf"), "md": os.path.join(base, f"workflow_{workflow_id}.md")}


def fallback_report(wf: Workflow, steps: list[WorkflowStep], note: str) -> str:
    parts = [f"# {wf.title}", f"> Generated without LLM narrative: {note}", "", "## Task", wf.description, "", "## Findings by step"]
    for s in steps:
        if s.step_type == "tool":
            body = (s.output_data or {}).get("summary") if s.status == "completed" else f"FAILED: {s.error}"
            parts += [f"### Step {s.step_number}: {s.name} ({s.tool_name})", body or "(no output)", ""]
    return "\n".join(parts)


def generate_report(db: Session, wf: Workflow, steps: list[WorkflowStep], validation: dict, llm: LLMClient) -> dict:
    evidence = build_evidence(steps)
    charts = [c for s in steps if s.status == "completed" for c in ((s.output_data or {}).get("charts") or [])]
    failed = [f"Step {s.step_number} ({s.tool_name}): {s.error}" for s in steps if s.step_type == "tool" and s.status == "failed"]
    user_msg = (f"TASK: {wf.description}\n\nEVIDENCE:\n{evidence}\n\nFAILED STEPS: {failed or 'none'}\n"
                f"VALIDATION WARNINGS: {validation.get('warnings') or 'none'}")
    used_llm, grounding, attempts = True, {}, 0
    try:
        messages = [{"role": "system", "content": REPORT_SYSTEM}, {"role": "user", "content": user_msg}]
        md = (llm.chat(messages, temperature=0.2, max_tokens=1800).get("content") or "").strip()
        if not md:
            raise LLMError("Empty report from model")
        grounding = check_grounding(llm, md, evidence)
        if grounding.get("grounded") is False and attempts == 0:
            attempts += 1
            fix = "Rewrite the report removing or correcting these unsupported claims: " + "; ".join(grounding["unsupported_claims"])
            md2 = (llm.chat(messages + [{"role": "assistant", "content": md}, {"role": "user", "content": fix}],
                            temperature=0.1, max_tokens=1800).get("content") or "").strip()
            if md2:
                md, grounding = md2, {**check_grounding(llm, md2, evidence), "regenerated": True}
    except LLMError as exc:
        logger.warning("Report LLM unavailable, using deterministic fallback: %s", exc)
        used_llm, grounding = False, {"grounded": None, "method": "skipped", "note": str(exc)[:200]}
        md = fallback_report(wf, steps, str(exc)[:200])

    paths = report_paths(wf.id)
    os.makedirs(os.path.dirname(paths["pdf"]), exist_ok=True)
    with open(paths["md"], "w", encoding="utf-8") as fh:
        fh.write(md)
    render_pdf(paths["pdf"], wf.title, md, charts)
    return {"summary": f"Report generated ({len(md.split())} words, {len(charts)} charts, "
                       f"grounding: {grounding.get('score', 'n/a')}).",
            "data": {"report_markdown": md, "grounding": grounding, "used_llm": used_llm},
            "charts": charts}


def ensure_report_files(wf: Workflow) -> dict:
    """Rebuild the PDF/Markdown from the stored result when the filesystem was reset (ephemeral hosts)."""
    paths = report_paths(wf.id)
    if wf.result and not (os.path.exists(paths["pdf"]) and os.path.exists(paths["md"])):
        os.makedirs(os.path.dirname(paths["pdf"]), exist_ok=True)
        md = wf.result.get("report_markdown", "")
        with open(paths["md"], "w", encoding="utf-8") as fh:
            fh.write(md)
        render_pdf(paths["pdf"], wf.title, md, wf.result.get("charts") or [])
    return paths
