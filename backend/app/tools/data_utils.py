"""Shared dataset loading + column detection. Built to cope with messy real-world (e.g. Kaggle) files:
odd encodings/delimiters, currency strings, day-first dates, Year+Month columns, Excel dates, missing date columns."""
import warnings

import pandas as pd
from sqlalchemy import select

from app.models import Document
from app.tools.base import ToolContext, ToolError
from app.utils.files import ensure_local_file

DATASET_TYPES = ("csv", "xlsx")
VALUE_HINTS = ["revenue", "sales", "amount", "total", "profit", "value", "units", "quantity", "price", "cost"]
GROUP_HINTS = ["region", "category", "segment", "product", "state", "country", "channel", "team", "department",
               "city", "customer", "dealsize", "line", "type", "market"]
DATE_HINTS = ["date", "time", "period", "month", "day", "timestamp"]
NOT_A_METRIC = ("id", "zip", "postal", "code", "year", "month", "day", "qtr", "quarter", "row", "index", "number",
                "phone", "lat", "lon")
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


# ----------------------------------------------------------------------------- loading
def find_document(ctx: ToolContext, ref: str | int | None, datasets_only: bool = True) -> Document:
    q = select(Document).where(Document.user_id == ctx.user_id, Document.status == "ready")
    if datasets_only:
        q = q.where(Document.file_type.in_(DATASET_TYPES))
    docs = list(ctx.db.scalars(q.order_by(Document.created_at.desc())))
    if not docs:
        raise ToolError("No ready dataset (CSV/XLSX) found. Upload one on the Documents page first.")
    if ref in (None, ""):
        return docs[0]
    sref = str(ref).strip().lower()
    for d in docs:
        if str(d.id) == sref or d.filename.lower() == sref:
            return d
    for d in docs:
        if sref in d.filename.lower():
            return d
    return docs[0]  # an unknown name from the LLM should not kill the step; fall back to the newest dataset


def _read_table(doc: Document) -> pd.DataFrame:
    try:
        path = ensure_local_file(doc)
    except FileNotFoundError as exc:
        raise ToolError(str(exc)) from exc
    if doc.file_type == "xlsx":
        return pd.read_excel(path)
    last: Exception | None = None
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return pd.read_csv(path, encoding=enc, sep=None, engine="python")  # sniffs , ; | tab
        except UnicodeDecodeError as exc:
            last = exc
        except pd.errors.ParserError as exc:
            last = exc
            break
    try:
        return pd.read_csv(path, encoding="latin-1", on_bad_lines="skip")
    except Exception as exc:  # noqa: BLE001
        raise ToolError(f"Could not read {doc.filename}: {exc or last}") from exc


def _clean_number_strings(s: pd.Series) -> pd.Series:
    out = s.astype(str).str.strip().str.replace(r"^\((.*)\)$", r"-\1", regex=True)
    return out.str.replace(r"[,$\u20ac\u00a3\u20b9%\s]", "", regex=True)


def _coerce_numeric_columns(df: pd.DataFrame) -> pd.DataFrame:
    for c in df.columns:
        if df[c].dtype != object or any(t in c.lower() for t in ("id", "zip", "postal", "code", "phone")):
            continue
        sample = df[c].dropna().head(2000)
        if sample.empty:
            continue
        if pd.to_numeric(_clean_number_strings(sample), errors="coerce").notna().mean() >= 0.9:
            df[c] = pd.to_numeric(_clean_number_strings(df[c].where(df[c].notna(), "")), errors="coerce")
    return df


def load_dataframe(doc: Document) -> pd.DataFrame:
    df = _read_table(doc)
    df.columns = [str(c).strip() for c in df.columns]
    df = df.loc[:, ~df.columns.str.match(r"^Unnamed")].dropna(how="all")
    if df.empty:
        raise ToolError(f"{doc.filename} contains no rows.")
    return _coerce_numeric_columns(df)


# ----------------------------------------------------------------------------- column detection
def _lookup(df: pd.DataFrame, name: str | None) -> str | None:
    if not name:
        return None
    lk = {c.lower(): c for c in df.columns}
    key = str(name).strip().lower()
    if key in lk:
        return lk[key]
    return next((orig for low, orig in lk.items() if key in low or (len(low) >= 4 and low in key)), None)


def _parse_dates(s: pd.Series) -> pd.Series | None:
    """Best-effort datetime parse; returns None if fewer than 80% of values parse."""
    if pd.api.types.is_datetime64_any_dtype(s):
        return s
    if pd.api.types.is_numeric_dtype(s):
        v = s.dropna()
        if not v.empty and v.between(19000101, 21001231).all() and (v % 1 == 0).all():  # 20190131
            p = pd.to_datetime(v.astype("int64").astype(str), format="%Y%m%d", errors="coerce").reindex(s.index)
            return p if p.notna().mean() >= 0.8 else None
        return None
    sample = s.dropna().astype(str).head(2000)
    if sample.empty:
        return None
    best_kw, best_ratio = None, 0.0
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for kw in ({}, {"dayfirst": True}):
            ratio = pd.to_datetime(sample, errors="coerce", **kw).notna().mean()
            if ratio > best_ratio:
                best_kw, best_ratio = kw, ratio
        if best_ratio < 0.8:
            return None
        return pd.to_datetime(s, errors="coerce", **(best_kw or {}))


def _year_month_date(df: pd.DataFrame) -> pd.Series | None:
    low = {c.lower(): c for c in df.columns}
    ycol = next((low[k] for k in ("year", "year_id", "yr") if k in low), None)
    mcol = next((low[k] for k in ("month", "month_id", "month_name", "monthname", "mon") if k in low), None)
    if not (ycol and mcol):
        return None
    m = df[mcol]
    if not pd.api.types.is_numeric_dtype(m):
        m = m.astype(str).str.strip().str[:3].str.lower().map(MONTHS)
    y = pd.to_numeric(df[ycol], errors="coerce")
    out = pd.to_datetime(dict(year=y, month=pd.to_numeric(m, errors="coerce"), day=1), errors="coerce")
    return out if out.notna().mean() >= 0.8 else None


def detect_columns(df: pd.DataFrame, date=None, value=None, group=None) -> dict:
    """Resolve date/value/group columns. Names suggested by the LLM that don't exist are ignored (auto-detected)
    rather than failing. May add a parsed '_date' column to df. Returns {'date','value','group','notes'}."""
    notes: list[str] = []
    asked = {"date": date, "value": value, "group": group}
    date, value, group = _lookup(df, date), _lookup(df, value), _lookup(df, group)
    for key, found in (("date", date), ("value", value), ("group", group)):
        if asked[key] and not found:
            notes.append(f"Requested {key} column '{asked[key]}' not found; auto-detected instead.")

    if date:
        parsed = _parse_dates(df[date])
        if parsed is None:
            notes.append(f"Column '{date}' is not a valid date column; auto-detecting.")
            date = None
        else:
            df["_date"], date = parsed, "_date"
    if not date:
        hinted = [c for c in df.columns if any(h in c.lower() for h in DATE_HINTS)]
        for c in hinted + [c for c in df.columns if c not in hinted]:
            if c.startswith("_") or (pd.api.types.is_numeric_dtype(df[c]) and not pd.api.types.is_datetime64_any_dtype(df[c]) and c not in hinted):
                continue
            parsed = _parse_dates(df[c])
            if parsed is not None and parsed.dt.year.nunique() >= 1:
                df["_date"], date = parsed, "_date"
                notes.append(f"Using '{c}' as the date column.")
                break
    if not date:
        parsed = _year_month_date(df)
        if parsed is not None:
            df["_date"], date = parsed, "_date"
            notes.append("Built a date from the Year and Month columns.")

    numeric = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) and c != "_date"
               and not pd.api.types.is_bool_dtype(df[c])]
    if not value and numeric:
        metrics = [c for c in numeric if not any(t in c.lower() for t in NOT_A_METRIC)] or numeric
        value = next((c for h in VALUE_HINTS for c in metrics if h in c.lower()), metrics[0])
    if not group:
        n = len(df)
        cats = [c for c in df.columns if c not in ("_date", value) and not pd.api.types.is_numeric_dtype(df[c])
                and not pd.api.types.is_datetime64_any_dtype(df[c]) and 2 <= df[c].nunique() <= 60
                and df[c].nunique() < max(n * 0.5, 3)]
        group = next((c for h in GROUP_HINTS for c in cats if h in c.lower()), cats[0] if cats else None)
    return {"date": date, "value": value, "group": group, "notes": notes}


# ----------------------------------------------------------------------------- aggregation
def pick_freq(dates: pd.Series, requested: str | None = None) -> str:
    mapping = {"day": "D", "week": "W", "month": "M", "quarter": "Q"}
    if requested in mapping:
        return mapping[requested]
    span = (dates.max() - dates.min()).days
    return "M" if span >= 90 else ("W" if span >= 21 else "D")


def aggregate_table(df: pd.DataFrame, cols: dict, aggregate: str = "sum", period: str | None = None):
    """Returns (pivot[period x group], freq, work_df). Without a group column the pivot has one 'Total' column."""
    if not cols["date"] or not cols["value"]:
        raise ToolError("No usable date column or numeric metric column was found in this dataset.")
    work = df[[c for c in dict.fromkeys([cols["date"], cols["value"], cols["group"]]) if c]].copy()
    work[cols["date"]] = pd.to_datetime(work[cols["date"]], errors="coerce")
    work[cols["value"]] = pd.to_numeric(work[cols["value"]], errors="coerce")
    work = work.dropna(subset=[cols["date"], cols["value"]])
    if work.empty:
        raise ToolError("No valid rows after parsing dates and numeric values.")
    freq = pick_freq(work[cols["date"]], period)
    work["_period"] = work[cols["date"]].dt.to_period(freq)
    agg = aggregate if aggregate in ("sum", "mean", "count", "median") else "sum"
    if cols["group"]:
        pv = work.pivot_table(index="_period", columns=cols["group"], values=cols["value"], aggfunc=agg, fill_value=0)
    else:
        pv = work.groupby("_period")[cols["value"]].agg(agg).to_frame("Total")
    pv = pv.sort_index()
    full = pd.period_range(pv.index.min(), pv.index.max(), freq=freq)  # contiguous periods
    return pv.reindex(full, fill_value=0), freq, work


def partial_last_period_warning(work: pd.DataFrame, date_col: str, freq: str) -> str | None:
    """Warn when the newest period has far fewer active days than earlier ones (would look like a false 'drop')."""
    if freq not in ("M", "W", "Q"):
        return None
    days = work.assign(_d=work[date_col].dt.normalize()).groupby("_period")["_d"].nunique()
    if len(days) < 3:
        return None
    if days.iloc[-1] < 0.6 * days.iloc[:-1].median():
        return (f"The latest period ({days.index[-1]}) has data for only {days.iloc[-1]} days vs a typical "
                f"{int(days.iloc[:-1].median())}; it may be incomplete, so drops in it can be overstated.")
    return None


def group_summary(df: pd.DataFrame, cols: dict, aggregate: str = "sum") -> pd.DataFrame:
    """Static (no time axis) summary of the metric per group, with share of total."""
    if not cols["value"]:
        raise ToolError("This dataset has no numeric column to analyze. Columns: " + ", ".join(df.columns[:20]))
    agg = aggregate if aggregate in ("sum", "mean", "count", "median") else "sum"
    v = pd.to_numeric(df[cols["value"]], errors="coerce")
    if cols["group"]:
        t = v.groupby(df[cols["group"]]).agg([agg, "count", "mean"]).rename(columns={agg: "total"})
    else:
        t = pd.DataFrame({"total": [getattr(v, agg)()], "count": [v.count()], "mean": [v.mean()]}, index=["All rows"])
    t["share_pct"] = t["total"] / t["total"].sum() * 100 if t["total"].sum() else 0
    return t.sort_values("total", ascending=False)
