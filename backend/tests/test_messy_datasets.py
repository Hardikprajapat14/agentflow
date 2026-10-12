"""Kaggle-style files: odd encodings, currency strings, day-first dates, Year+Month columns, no date, one period."""
import uuid

import numpy as np
import pandas as pd
import pytest

from app.database import SessionLocal
from app.models import Document, User
from app.tools import REGISTRY, ToolContext, ToolError


@pytest.fixture()
def run(tmp_path):
    db = SessionLocal()
    user = User(email=f"m{uuid.uuid4().hex[:8]}@example.com", password_hash="x", name="m")
    db.add(user)
    db.commit()

    def _run(tool: str, frame: pd.DataFrame | None = None, ext="csv", args=None, raw: bytes | None = None, **save):
        path = tmp_path / f"{uuid.uuid4().hex}.{ext}"
        if raw is not None:
            path.write_bytes(raw)
        elif ext == "csv":
            frame.to_csv(path, index=False, **save)
        else:
            frame.to_excel(path, index=False)
        doc = Document(user_id=user.id, filename=path.name, file_type=ext, file_size=1, status="ready", storage_path=str(path))
        db.add(doc)
        db.commit()
        return REGISTRY[tool].run(args or {}, ToolContext(db, user.id, 0, "test"))

    yield _run
    db.close()


def base(n=400, seed=1):
    rng = np.random.default_rng(seed)
    d = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame({"Order Date": d, "Region": rng.choice(["East", "West", "South"], n),
                         "Sales": rng.uniform(10, 500, n).round(2), "Quantity": rng.integers(1, 9, n)})


def test_dayfirst_dates_and_currency_strings(run):
    df = base()
    df["Order Date"] = df["Order Date"].dt.strftime("%d/%m/%Y")        # 31/01/2024 style
    df["Sales"] = df["Sales"].map(lambda v: f"${v:,.2f}")                # "$1,234.50"
    r = run("analyze_data", df)
    assert r.data["columns_used"]["value"] == "Sales" and "2024-01" in r.data["periods"] and len(r.data["periods"]) >= 12


def test_latin1_semicolon_csv(run):
    df = base()
    df["Region"] = df["Region"].replace({"East": "Est\u00e9"})
    raw = df.to_csv(index=False, sep=";", decimal=",").encode("latin-1")
    r = run("analyze_data", raw=raw)
    assert r.data["columns_used"]["value"] in ("Sales", "Quantity") and r.data["by_group"]


def test_year_and_month_columns_without_date(run):
    rng = np.random.default_rng(3)
    rows = [{"YEAR_ID": y, "MONTH_ID": m, "COUNTRY": c, "SALES": float(rng.uniform(1e3, 9e3))}
            for y in (2003, 2004) for m in range(1, 13) for c in ("USA", "France", "Spain") for _ in range(3)]
    r = run("analyze_data", pd.DataFrame(rows))
    assert r.data["columns_used"]["value"] == "SALES" and len(r.data["periods"]) == 24
    assert any("Year and Month" in n for n in r.data["notes"])


def test_no_date_column_falls_back_to_group_ranking(run):
    df = base().drop(columns=["Order Date"])
    r = run("analyze_data", df)
    assert r.data["mode"] == "static" and r.data["by_group"] and "No date column" in r.summary
    c = run("create_chart", df)                                          # chart works without dates too
    assert c.charts[0]["type"] == "bar"
    m = run("ml_analysis", df)                                           # row-level outliers
    assert m.data["anomalies"]


def test_single_period_dataset(run):
    df = base(25)
    df["Order Date"] = "2024-03-15"                                       # every row on one date -> one period
    assert run("analyze_data", df).data["mode"] == "static"


def test_llm_supplied_wrong_column_names_are_ignored(run):
    r = run("analyze_data", base(), args={"date_column": "TransactionDate", "value_column": "Revenue", "group_column": "Area"})
    assert r.data["columns_used"]["value"] == "Sales" and any("not found" in n for n in r.data["notes"])


def test_excel_with_real_dates_and_numeric_yyyymmdd(run):
    assert run("analyze_data", base(), ext="xlsx").data["periods"]
    df = base()
    df["Order Date"] = df["Order Date"].dt.strftime("%Y%m%d").astype(int)
    assert len(run("analyze_data", df).data["periods"]) >= 12


def test_partial_last_month_is_flagged(run):
    df = base(400)
    df = df[~((df["Order Date"] > "2025-01-05"))]                         # last month has only a few days
    r = run("analyze_data", df)
    assert r.data["warnings"] and "incomplete" in r.data["warnings"][0]


def test_no_numeric_column_gives_clear_error(run):
    with pytest.raises(ToolError, match="numeric"):
        run("analyze_data", pd.DataFrame({"a": ["x", "y", "z"] * 5, "b": ["p", "q", "r"] * 5}))


def test_dataset_survives_wiped_disk_and_db_url_is_normalised(run, tmp_path):
    import os
    from app.config import Settings

    assert Settings(database_url="postgres://u:p@h/db").database_url == "postgresql+psycopg2://u:p@h/db"
    assert Settings(database_url="postgresql://u:p@h/db").database_url.startswith("postgresql+psycopg2://")
    db = SessionLocal()
    user = User(email=f"w{uuid.uuid4().hex[:8]}@example.com", password_hash="x", name="w")
    db.add(user)
    db.commit()
    path = tmp_path / "gone.csv"
    base().to_csv(path, index=False)
    doc = Document(user_id=user.id, filename="gone.csv", file_type="csv", file_size=1, status="ready",
                   storage_path=str(path), content=path.read_bytes())
    db.add(doc)
    db.commit()
    os.remove(path)                                                       # simulate Render's ephemeral disk reset
    res = REGISTRY["analyze_data"].run({}, ToolContext(db, user.id, 0, "t"))
    assert res.data["by_group"]
    db.close()
