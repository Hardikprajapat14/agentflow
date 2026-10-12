import pandas as pd

from app.agents.validator import validate_workflow
from app.models import WorkflowStep
from app.rag.chunking import split_text
from app.rag.embeddings import embed_texts
from app.security.auth import create_access_token, decode_token, hash_password, verify_password
from app.services.llm import extract_json
from app.tools.data_utils import aggregate_table, detect_columns
from app.ml.anomaly import detect_anomalies, forecast_next


def test_password_hashing_and_long_passwords():
    pw = "x" * 200
    h = hash_password(pw)
    assert h != pw and verify_password(pw, h)
    assert not verify_password(pw[:-1], h)


def test_jwt_roundtrip_and_tamper():
    tok = create_access_token(42)
    assert decode_token(tok) == 42
    assert decode_token(tok + "x") is None
    assert decode_token("garbage") is None


def test_extract_json_handles_fences_and_prose():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('Sure! {"a": {"b": 2}} done') == {"a": {"b": 2}}


def test_chunking_overlap_and_limits():
    text = "\n\n".join(f"Paragraph {i}. " + "word " * 80 for i in range(10))
    chunks = split_text(text, chunk_size=500, overlap=50)
    assert len(chunks) > 5 and all(len(c) <= 560 for c in chunks)
    assert split_text("   ") == []


def test_hashing_embeddings_are_normalised_and_similar_texts_closer():
    a, b, c = embed_texts(["discount approval policy", "policy on discount approval", "quarterly rainfall in kenya"])
    dot = lambda x, y: sum(i * j for i, j in zip(x, y))  # noqa: E731
    assert len(a) == 384 and abs(dot(a, a) - 1) < 1e-6
    assert dot(a, b) > dot(a, c)


def _sales(sample_dir):
    return pd.read_csv(sample_dir / "sales_data.csv")


def test_column_detection_and_aggregation(sample_dir):
    df = _sales(sample_dir)
    cols = detect_columns(df)
    assert cols["value"] == "revenue" and cols["group"] == "region" and cols["date"] == "_date"
    pv, freq, _ = aggregate_table(df, cols)
    assert freq == "M" and len(pv) == 12 and set(pv.columns) == {"North", "South", "East", "West", "Central"}


def test_ml_detects_planted_anomalies_and_forecasts(sample_dir):
    df = _sales(sample_dir)
    pv, _, _ = aggregate_table(df, detect_columns(df))
    anomalies, _ = detect_anomalies(pv)
    assert any(a["group"] == "Central" and a["period"] == "2026-03" for a in anomalies)
    assert any(a["group"] == "West" and a["period"] == "2026-09" for a in anomalies)
    fc = forecast_next(pv)
    assert len(fc) == 5 and fc[0]["next_period"] == "2026-10"


def _step(n, tool, status="completed", out=None, error=None):
    return WorkflowStep(step_number=n, name=tool, step_type="tool", tool_name=tool, status=status,
                        output_data=out, error=error)


def test_validator_flags_failed_critical_step_but_tolerates_web_failure():
    ok = validate_workflow([_step(2, "analyze_data", out={"summary": "x", "data": {"totals_by_period": {"a": 1}}}),
                            _step(3, "web_search", "failed", error="offline")])
    assert ok["passed"] and ok["warnings"]
    bad = validate_workflow([_step(2, "analyze_data", "failed", error="boom")])
    assert not bad["passed"]
