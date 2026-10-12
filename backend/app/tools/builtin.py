"""Built-in tools. Each tool does real work: pandas/scikit-learn analysis, pgvector retrieval, live web search, SMTP."""
import re
import smtplib
from email.message import EmailMessage

import pandas as pd

from app.config import get_settings
from app.ml.anomaly import detect_anomalies, forecast_next
from app.models import DocumentChunk
from app.rag.store import search as rag_search_chunks
from app.tools.base import Tool, ToolContext, ToolError, ToolResult, register
from app.tools.data_utils import (aggregate_table, detect_columns, find_document, group_summary, load_dataframe,
                                  partial_last_period_warning)

DOC_PROP = {"type": "string", "description": "Dataset filename or id. Defaults to the most recent CSV/XLSX upload."}


FREQ_NAMES = {"M": "month", "W": "week", "D": "day", "Q": "quarter"}


def _fmt(n) -> str:
    return f"{n:,.0f}" if abs(n) >= 100 else f"{n:,.2f}"


# --------------------------------------------------------------------------- read_document
def read_document(args: dict, ctx: ToolContext) -> ToolResult:
    ref = args.get("document")
    doc = find_document(ctx, ref, datasets_only=False)
    if doc.file_type in ("csv", "xlsx"):
        df = load_dataframe(doc)
        nulls = {c: int(v) for c, v in df.isna().sum().items() if v}
        desc = df.describe(include="number").round(2).to_dict() if df.select_dtypes("number").shape[1] else {}
        data = {"filename": doc.filename, "rows": len(df), "columns": {c: str(t) for c, t in df.dtypes.items()},
                "sample": df.head(5).astype(str).to_dict(orient="records"), "numeric_summary": desc,
                "missing_values": nulls, "duplicate_rows": int(df.duplicated().sum())}
        return ToolResult(f"Read dataset '{doc.filename}': {len(df):,} rows x {df.shape[1]} columns "
                          f"({', '.join(df.columns[:12])}). Missing cells: {sum(nulls.values())}; "
                          f"duplicate rows: {data['duplicate_rows']}.", data)
    chunks = [c.content for c in ctx.db.query(DocumentChunk).filter(DocumentChunk.document_id == doc.id)
              .order_by(DocumentChunk.chunk_index).limit(4)]
    total = ctx.db.query(DocumentChunk).filter(DocumentChunk.document_id == doc.id).count()
    excerpt = "\n\n".join(chunks)[:2500]
    return ToolResult(f"Read document '{doc.filename}' ({total} indexed chunks). Excerpt:\n{excerpt[:600]}",
                      {"filename": doc.filename, "chunks": total, "excerpt": excerpt})


register(Tool("read_document", "Extract and inspect an uploaded file: schema, sample rows and data quality for CSV/XLSX, "
              "or a text excerpt for PDF/DOCX/TXT.",
              {"type": "object", "properties": {"document": {"type": "string", "description": "Filename or id of any uploaded file."}}},
              read_document))


# --------------------------------------------------------------------------- analyze_data
def _static_analysis(doc, df, cols, aggregate, reason: str) -> ToolResult:
    """Fallback when there is no usable time axis: rank groups by the metric and describe the distribution."""
    t = group_summary(df, cols, aggregate)
    rows = [{"group": str(i), "total": float(r.total), "count": int(r["count"]), "mean": float(r["mean"]),
             "share_pct": round(float(r.share_pct), 1)} for i, r in t.iterrows()]
    label = cols["group"] or "all rows"
    lines = [f"Dataset '{doc.filename}': {len(df):,} rows. {reason}",
             f"Metric: {cols['value']}; grouped by: {label}. Grand total: {_fmt(t['total'].sum())}."]
    if cols["group"] and len(rows) > 1:
        top, bottom = rows[0], rows[-1]
        lines.append(f"Top {cols['group']}: {top['group']} ({_fmt(top['total'])}, {top['share_pct']}% of total). "
                     f"Lowest: {bottom['group']} ({_fmt(bottom['total'])}, {bottom['share_pct']}%).")
        lines.append("Ranking: " + "; ".join(f"{r['group']} {_fmt(r['total'])} ({r['share_pct']}%)" for r in rows[:8]))
    return ToolResult("\n".join(lines), {"columns_used": cols, "mode": "static", "by_group": rows, "drops": [],
                                         "totals_by_period": {"all": round(float(t["total"].sum()), 2)},
                                         "data_quality": {"rows": len(df), "missing_cells": int(df.isna().sum().sum()),
                                                          "duplicate_rows": int(df.duplicated().sum())},
                                         "notes": cols.get("notes", [])})


def analyze_data(args: dict, ctx: ToolContext) -> ToolResult:
    doc = find_document(ctx, args.get("document"))
    df = load_dataframe(doc)
    cols = detect_columns(df, args.get("date_column"), args.get("value_column"), args.get("group_column"))
    agg = args.get("aggregate", "sum")
    if not cols["value"]:
        raise ToolError("No numeric column found to analyze. Columns in this file: " + ", ".join(df.columns[:25]))
    if not cols["date"]:
        return _static_analysis(doc, df, cols, agg, "No date column was found, so trends over time were not analyzed.")
    pv, freq, work = aggregate_table(df, cols, agg, args.get("period"))
    if len(pv) < 2:
        return _static_analysis(doc, df, cols, agg, "Only one time period exists in the data, so no period-over-period "
                                                    "comparison is possible.")
    threshold = float(args.get("drop_threshold_pct", 10)) / 100
    last, prev = pv.index[-1], pv.index[-2]
    history = pv.iloc[:-1]
    groups = []
    for g in pv.columns:
        s = pv[g].astype(float)
        base = float(s[prev])
        chg = (float(s[last]) - base) / base if base else None
        hist_mean, hist_std = float(history[g].mean()), float(history[g].std(ddof=0))
        groups.append({"group": str(g), "total": float(s.sum()), "last_period": float(s[last]),
                       "previous_period": base, "change_pct": None if chg is None else round(chg * 100, 1),
                       "vs_history_avg_pct": round((float(s[last]) - hist_mean) / hist_mean * 100, 1) if hist_mean else None,
                       "z_vs_history": round((float(s[last]) - hist_mean) / hist_std, 2) if hist_std else None})
    groups.sort(key=lambda r: (r["change_pct"] is None, r["change_pct"] or 0))
    drops = [g for g in groups if g["change_pct"] is not None and g["change_pct"] <= -threshold * 100]
    totals = pv.sum(axis=1)
    tchg = (totals[last] - totals[prev]) / totals[prev] * 100 if totals[prev] else None
    quality = {"rows": len(df), "missing_cells": int(df.isna().sum().sum()), "duplicate_rows": int(df.duplicated().sum())}
    warn = partial_last_period_warning(work, cols["date"], freq)
    lines = [f"Dataset '{doc.filename}': {len(df):,} rows. Columns used -> date: {cols['date']}, "
             f"value: {cols['value']}, group: {cols['group']}. Periods ({freq}): {pv.index[0]} to {last}.",
             f"Grand total {cols['value']}: {_fmt(totals.sum())}. Latest period {last}: {_fmt(totals[last])}"
             + (f" ({tchg:+.1f}% vs {prev})." if tchg is not None else ".")]
    if cols["group"]:
        top = max(groups, key=lambda r: r["total"])
        lines.append(f"Largest {cols['group']} overall: {top['group']} ({_fmt(top['total'])}).")
        if drops:
            lines.append(f"Drops of {threshold*100:.0f}%+ in {last} vs {prev}: " + "; ".join(
                f"{d['group']} {d['change_pct']:+.1f}% ({_fmt(d['previous_period'])} -> {_fmt(d['last_period'])}"
                + (f", {d['vs_history_avg_pct']:+.1f}% vs its historical avg)" if d["vs_history_avg_pct"] is not None else ")")
                for d in drops[:10]))
        else:
            lines.append(f"No {cols['group']} dropped by {threshold*100:.0f}% or more in {last}.")
    if warn:
        lines.append("WARNING: " + warn)
    return ToolResult("\n".join(lines), {
        "columns_used": cols, "period_frequency": freq, "periods": [str(p) for p in pv.index],
        "totals_by_period": {str(p): round(float(v), 2) for p, v in totals.items()},
        "by_group": groups[:50], "drops": drops[:20], "data_quality": quality,
        "drop_threshold_pct": threshold * 100, "warnings": [warn] if warn else [], "notes": cols.get("notes", [])})


_ANALYSIS_PROPS = {
    "document": DOC_PROP,
    "date_column": {"type": "string", "description": "Date column name (auto-detected if omitted)."},
    "value_column": {"type": "string", "description": "Numeric metric to analyze, e.g. revenue (auto-detected)."},
    "group_column": {"type": "string", "description": "Dimension to compare, e.g. region (auto-detected)."},
    "aggregate": {"type": "string", "enum": ["sum", "mean", "count", "median"]},
    "period": {"type": "string", "enum": ["day", "week", "month", "quarter"]},
}
register(Tool("analyze_data", "Aggregate a dataset by time period and group, compute period-over-period change, "
              "compare the latest period with history and flag drops. Works without a date column (ranks groups).",
              {"type": "object", "properties": {**_ANALYSIS_PROPS, "drop_threshold_pct": {"type": "number", "description": "Flag drops at least this large (default 10)."}}},
              analyze_data))


# --------------------------------------------------------------------------- ml_analysis
def _row_outliers(doc, df, cols, contamination: float) -> ToolResult:
    """No usable time series: Isolation Forest over the numeric columns to find unusual rows."""
    from sklearn.ensemble import IsolationForest

    num = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) and c != "_date"
           and not any(t in c.lower() for t in ("id", "zip", "postal", "code", "row", "index"))][:8]
    if not num or len(df) < 20:
        raise ToolError("Not enough numeric data for ML analysis (need a numeric column and at least 20 rows).")
    x = df[num].apply(pd.to_numeric, errors="coerce")
    x = x.fillna(x.median()).fillna(0)
    model = IsolationForest(n_estimators=200, contamination=min(max(contamination, 0.01), 0.1), random_state=42).fit(x)
    score = -model.score_samples(x)
    idx = score.argsort()[::-1][:10]
    keep = [c for c in dict.fromkeys([cols["group"], cols["value"], *num[:4]]) if c]
    out = [{"row": int(i) + 2, "anomaly_score": round(float(score[i]), 3), **{c: str(df.iloc[i][c]) for c in keep}} for i in idx]
    summary = (f"ML analysis on '{doc.filename}': no usable time series, so IsolationForest was run on rows using "
               f"{', '.join(num)}. Most unusual rows (file row numbers): "
               + "; ".join(f"row {o['row']} (score {o['anomaly_score']}, {cols['value']}={o.get(cols['value'], 'n/a')})" for o in out[:5]))
    return ToolResult(summary, {"method": "IsolationForest on numeric columns (row level)", "anomalies": out,
                                "forecasts": [], "columns_used": cols})


def ml_analysis(args: dict, ctx: ToolContext) -> ToolResult:
    doc = find_document(ctx, args.get("document"))
    df = load_dataframe(doc)
    cols = detect_columns(df, args.get("date_column"), args.get("value_column"), args.get("group_column"))
    contamination = float(args.get("contamination", 0.08))
    if not cols["value"]:
        raise ToolError("No numeric column found for ML analysis. Columns: " + ", ".join(df.columns[:25]))
    if not cols["date"]:
        return _row_outliers(doc, df, cols, contamination)
    pv, freq, _ = aggregate_table(df, cols, args.get("aggregate", "sum"), args.get("period"))
    if len(pv) < 3:
        return _row_outliers(doc, df, cols, contamination)
    anomalies, method = detect_anomalies(pv, contamination)
    forecasts = forecast_next(pv)
    lines = [f"ML analysis on '{doc.filename}' ({cols['value']} by {cols['group'] or 'total'} per {FREQ_NAMES.get(freq, freq)}) using {method}."]
    if anomalies:
        lines.append("Top anomalies: " + "; ".join(
            f"{a['group']} {a['period']} ({a['direction']}, value {_fmt(a['value'])}"
            + (f", {a['pct_change']:+.1f}% vs prior" if a['pct_change'] is not None else "") + ")" for a in anomalies[:6]))
    else:
        lines.append("No statistical anomalies detected.")
    if forecasts:
        lines.append(f"Linear-trend forecast for {forecasts[0]['next_period']}: " + "; ".join(
            f"{f['group']} {_fmt(f['forecast'])} (trend {f['trend_per_period']:+,.0f}/period, R2={f['r2']})" for f in forecasts[:6]))
    return ToolResult("\n".join(lines), {"method": method, "anomalies": anomalies, "forecasts": forecasts,
                                         "columns_used": cols})


register(Tool("ml_analysis", "Machine-learning analysis: Isolation Forest anomaly detection and linear-trend forecasting "
              "per group over time (falls back to row-level outlier detection if there is no time axis).",
              {"type": "object", "properties": {**_ANALYSIS_PROPS, "contamination": {"type": "number", "description": "Expected anomaly share 0.01-0.3 (default 0.08)."}}},
              ml_analysis))


# --------------------------------------------------------------------------- create_chart
def create_chart(args: dict, ctx: ToolContext) -> ToolResult:
    doc = find_document(ctx, args.get("document"))
    df = load_dataframe(doc)
    kind = args.get("chart_type", "line")
    cols = detect_columns(df, None, args.get("y_column"), args.get("group_column"))
    if not cols["value"]:
        raise ToolError("No numeric column found to chart. Columns: " + ", ".join(df.columns[:25]))
    agg = args.get("aggregate", "sum")
    title = args.get("title") or f"{cols['value']} by {cols['group'] or 'period'}"
    if not cols["date"]:
        kind = "bar"  # no time axis -> compare groups
    if kind == "bar":
        if cols["group"]:
            t = group_summary(df, cols, agg)["total"].head(30)
            series, rows = [cols["value"]], [{"x": str(k), cols["value"]: round(float(v), 2)} for k, v in t.items()]
        else:
            pv, _, _ = aggregate_table(df, cols, agg, args.get("period"))
            series, rows = [cols["value"]], [{"x": str(p), cols["value"]: round(float(v), 2)} for p, v in pv["Total"].items()]
    else:
        pv, freq, _ = aggregate_table(df, cols, agg, args.get("period"))
        keep = list(pv.sum().sort_values(ascending=False).head(8).index)
        series = [str(c) for c in keep]
        rows = [{"x": str(p), **{str(c): round(float(pv.loc[p, c]), 2) for c in keep}} for p in pv.index]
    chart = {"title": title, "type": kind, "series": series, "data": rows,
             "x_label": cols["group"] if kind == "bar" and cols["group"] else "period", "y_label": cols["value"]}
    return ToolResult(f"Created {chart['type']} chart '{title}' with {len(rows)} points and {len(series)} series.",
                      {"points": len(rows), "series": series}, charts=[chart])


register(Tool("create_chart", "Create a line chart (value over time, one line per group) or bar chart (totals per group) from a dataset.",
              {"type": "object", "properties": {"document": DOC_PROP, "chart_type": {"type": "string", "enum": ["line", "bar"]},
               "y_column": {"type": "string"}, "group_column": {"type": "string"}, "x_column": {"type": "string"},
               "aggregate": {"type": "string", "enum": ["sum", "mean", "count", "median"]},
               "title": {"type": "string"}}}, create_chart))


# --------------------------------------------------------------------------- rag_search
def rag_search(args: dict, ctx: ToolContext) -> ToolResult:
    query = args.get("query") or ctx.objective
    hits = rag_search_chunks(ctx.db, ctx.user_id, query, int(args.get("top_k", 5)))
    if not hits:
        return ToolResult("No indexed documents matched. Upload policy/reference documents on the Documents page.",
                          {"query": query, "passages": []})
    best = hits[0]
    lines = [f"Retrieved {len(hits)} passages for '{query}' (best match: {best['filename']}, score {best['score']})."]
    for h in hits[:4]:
        flat = re.sub(r"\s+", " ", h["content"])[:420]
        lines.append(f"[{h['filename']} #{h['chunk_index']}, score {h['score']}] {flat}")
    return ToolResult("\n".join(lines), {"query": query, "passages": hits})


register(Tool("rag_search", "Semantic search (pgvector RAG) over the user's uploaded documents, e.g. company policies.",
              {"type": "object", "properties": {"query": {"type": "string", "description": "What to look up, phrased as a search query."},
               "top_k": {"type": "integer", "minimum": 1, "maximum": 10}}, "required": ["query"]}, rag_search))


# --------------------------------------------------------------------------- web_search
def web_search(args: dict, ctx: ToolContext) -> ToolResult:
    query = args.get("query") or ctx.objective
    try:
        try:
            from ddgs import DDGS
        except ImportError:  # older package name
            from duckduckgo_search import DDGS  # type: ignore
        results = DDGS().text(query, max_results=int(args.get("max_results", 5)))
    except Exception as exc:  # noqa: BLE001
        raise ToolError(f"Web search is unavailable right now ({type(exc).__name__}: {exc}). "
                        "The workflow can continue without it.") from exc
    items = [{"title": r.get("title"), "url": r.get("href"), "snippet": (r.get("body") or "")[:300]} for r in results or []]
    if not items:
        return ToolResult(f"Web search for '{query}' returned no results.", {"query": query, "results": []})
    lines = [f"Web search '{query}' returned {len(items)} results:"] + [f"- {i['title']} ({i['url']}): {i['snippet'][:200]}" for i in items]
    return ToolResult("\n".join(lines), {"query": query, "results": items})


register(Tool("web_search", "Search the public web (DuckDuckGo, no API key) for external or current information.",
              {"type": "object", "properties": {"query": {"type": "string"}, "max_results": {"type": "integer", "minimum": 1, "maximum": 8}},
               "required": ["query"]}, web_search))


# --------------------------------------------------------------------------- send_email (sensitive)
def send_email(args: dict, ctx: ToolContext) -> ToolResult:
    s = get_settings()
    if not (s.smtp_host and s.smtp_from):
        raise ToolError("Email is not configured. Set SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD and SMTP_FROM in .env.")
    recipients = [r.strip() for r in re.split(r"[,;\s]+", str(args.get("to", ""))) if r.strip()]
    if not recipients or len(recipients) > 5 or not all(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", r) for r in recipients):
        raise ToolError("Provide 1-5 valid recipient email addresses.")
    body = args.get("body") or "\n\n".join(f"Step {n}: {o.get('summary', '')}" for n, o in sorted(ctx.prior.items()))
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = s.smtp_from, ", ".join(recipients), args.get("subject") or "AgentFlow results"
    msg.set_content(body)
    try:
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20) as smtp:
            smtp.starttls()
            if s.smtp_user:
                smtp.login(s.smtp_user, s.smtp_password)
            smtp.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:
        raise ToolError(f"Failed to send email: {exc}") from exc
    return ToolResult(f"Email sent to {', '.join(recipients)}.", {"to": recipients, "subject": msg["Subject"]})


register(Tool("send_email", "Send an email with results to recipients. SENSITIVE: always requires human approval.",
              {"type": "object", "properties": {"to": {"type": "string", "description": "Comma-separated recipient emails."},
               "subject": {"type": "string"}, "body": {"type": "string", "description": "Plain-text body (defaults to a digest of previous steps)."}},
               "required": ["to"]}, send_email, sensitive=True))
