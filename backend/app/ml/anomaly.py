"""ML analysis: Isolation Forest anomaly detection + linear-trend forecasting on a period x group table."""
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.linear_model import LinearRegression


def detect_anomalies(pv: pd.DataFrame, contamination: float = 0.08) -> tuple[list[dict], str]:
    rows = []
    for g in pv.columns:
        s = pv[g].astype(float)
        pct = s.pct_change().replace([np.inf, -np.inf], np.nan)
        z = (s - s.mean()) / (s.std(ddof=0) or 1.0)
        for p in pv.index:
            rows.append({"group": str(g), "period": str(p), "value": float(s[p]),
                         "pct_change": None if pd.isna(pct[p]) else float(pct[p]), "z": float(z[p])})
    df = pd.DataFrame(rows)
    feats = df[["z"]].assign(pct=df["pct_change"].fillna(0.0).clip(-1, 2))
    if len(df) >= 12:
        model = IsolationForest(n_estimators=200, contamination=min(max(contamination, 0.01), 0.3), random_state=42)
        model.fit(feats)
        df["score"] = -model.score_samples(feats)
        df["flag"] = model.predict(feats) == -1
        method = "IsolationForest(z-score, pct-change)"
    else:
        df["score"] = df["z"].abs()
        df["flag"] = df["z"].abs() > 2
        method = "z-score > 2 (too few points for IsolationForest)"
    out = df[df["flag"]].sort_values("score", ascending=False).head(15)
    return [
        {"group": r.group, "period": r.period, "value": round(r.value, 2),
         "pct_change": None if r.pct_change is None or pd.isna(r.pct_change) else round(r.pct_change * 100, 1),
         "direction": "high" if r.z > 0 else "low", "anomaly_score": round(float(r.score), 3)}
        for r in out.itertuples()
    ], method


def forecast_next(pv: pd.DataFrame) -> list[dict]:
    if len(pv) < 4:
        return []
    x = np.arange(len(pv)).reshape(-1, 1)
    nxt = str(pv.index[-1] + 1)
    out = []
    for g in pv.columns:
        y = pv[g].astype(float).values
        m = LinearRegression().fit(x, y)
        pred = float(m.predict([[len(pv)]])[0])
        out.append({"group": str(g), "next_period": nxt, "forecast": round(max(pred, 0), 2),
                    "trend_per_period": round(float(m.coef_[0]), 2), "r2": round(float(m.score(x, y)), 3),
                    "last_actual": round(float(y[-1]), 2)})
    return sorted(out, key=lambda r: r["forecast"], reverse=True)
