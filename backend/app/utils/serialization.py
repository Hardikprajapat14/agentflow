import datetime as dt
import json
import math

import numpy as np
import pandas as pd


def to_jsonable(o):
    """Recursively convert numpy / pandas / datetime values into JSON-safe Python values."""
    if o is None or isinstance(o, str):
        return o
    if isinstance(o, (bool, np.bool_)):
        return bool(o)
    if isinstance(o, (int, np.integer)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        f = float(o)
        return None if math.isnan(f) or math.isinf(f) else round(f, 6)
    if isinstance(o, (dt.datetime, dt.date, pd.Timestamp)):
        return o.isoformat()
    if isinstance(o, pd.Period):
        return str(o)
    if isinstance(o, dict):
        return {str(k): to_jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple, set, np.ndarray)):
        return [to_jsonable(v) for v in o]
    if isinstance(o, pd.Series):
        return to_jsonable(o.to_dict())
    if isinstance(o, pd.DataFrame):
        return to_jsonable(o.to_dict(orient="records"))
    return str(o)


def compact_json(o, max_chars: int = 1500) -> str:
    text = json.dumps(to_jsonable(o), separators=(",", ":"), ensure_ascii=False)
    return text if len(text) <= max_chars else text[: max_chars - 3] + "..."
