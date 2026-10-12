"""Generates sales_data.csv, sample_customers.csv and company_sales_policy.pdf (deterministic)."""
import os
import random
from datetime import date, timedelta

import numpy as np
import pandas as pd
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

HERE = os.path.dirname(os.path.abspath(__file__))
rng = np.random.default_rng(42)
random.seed(42)

REGIONS = {"North": 1.0, "South": 0.85, "East": 1.2, "West": 1.1, "Central": 0.7}
CATEGORIES = {"Hardware": 220.0, "Software": 140.0, "Services": 310.0}
REPS = {r: [f"{r[:2].upper()}-Rep{i}" for i in range(1, 4)] for r in REGIONS}
MONTHS = pd.period_range("2025-10", "2026-09", freq="M")

rows, oid = [], 1000
for mi, month in enumerate(MONTHS):
    for region, rw in REGIONS.items():
        for cat, price in CATEGORIES.items():
            for week in range(4):
                factor = rw * (1 + 0.02 * mi) * rng.normal(1, 0.06)
                if region == "West" and month == MONTHS[-1]:
                    factor *= 0.70          # planted: West drops ~30% in the latest month
                if region == "South" and month == MONTHS[-1]:
                    factor *= 0.84          # planted: South drops ~16%
                if region == "Central" and mi == 5:
                    factor *= 1.7           # planted: Central spike (anomaly) in March 2026
                units = max(1, int(rng.normal(40, 6) * factor))
                disc = float(np.round(rng.choice([0, 5, 10, 12, 15, 20], p=[.3, .25, .2, .1, .1, .05]), 0))
                unit_price = round(price * rng.normal(1, 0.04), 2)
                d = date(month.year, month.month, 1) + timedelta(days=week * 7 + int(rng.integers(0, 6)))
                oid += 1
                rows.append({"order_id": f"ORD-{oid}", "date": d.isoformat(), "region": region, "product_category": cat,
                             "sales_rep": random.choice(REPS[region]), "units": units, "unit_price": unit_price,
                             "discount_pct": disc, "revenue": round(units * unit_price * (1 - disc / 100), 2)})
pd.DataFrame(rows).to_csv(os.path.join(HERE, "sales_data.csv"), index=False)

cust = []
for i in range(1, 201):
    region = random.choice(list(REGIONS))
    seg = random.choices(["Enterprise", "Mid-Market", "SMB"], [.15, .35, .5])[0]
    base = {"Enterprise": 90000, "Mid-Market": 30000, "SMB": 6000}[seg]
    cust.append({"customer_id": f"C{i:04d}", "name": f"Customer {i}", "region": region, "segment": seg,
                 "signup_date": (date(2022, 1, 1) + timedelta(days=int(rng.integers(0, 1400)))).isoformat(),
                 "lifetime_value": round(float(base * rng.lognormal(0, 0.4)), 2),
                 "churned": bool(rng.random() < (0.08 if seg == "Enterprise" else 0.18 if seg == "Mid-Market" else 0.3))})
pd.DataFrame(cust).to_csv(os.path.join(HERE, "sample_customers.csv"), index=False)

POLICY = [
    ("Company Sales Policy (v3.2)", None),
    ("1. Purpose", "This policy defines how regional sales performance is measured, reviewed and escalated across Acme Corp."),
    ("2. Discount Limits", "Sales representatives may grant discounts of up to 10% without approval. Discounts above 10% and up to 15% require regional manager approval. Any discount above 15% requires written VP of Sales approval and must be logged in the CRM within 24 hours."),
    ("3. Regional Performance Review", "A region whose monthly revenue declines by more than 10% compared with the previous month triggers a mandatory performance review within 5 business days. A decline of more than 25% is a critical drop and must be escalated to the VP of Sales and the CFO within 2 business days, together with a written recovery plan."),
    ("4. Recovery Plans", "Recovery plans must identify root causes (pricing, pipeline, staffing, seasonality, competition), assign an owner, define measurable weekly targets and be reviewed every two weeks until revenue returns to within 5% of its trailing three-month average."),
    ("5. Anomaly Handling", "Revenue spikes that exceed 50% of the trailing average must be validated by Finance for one-off deals or data errors before being reported as organic growth."),
    ("6. Reporting Requirements", "Executive sales reports must include: total revenue and month-over-month change, a regional breakdown, a list of regions that breach review thresholds, and concrete recommended actions. Figures must be reconciled with the finance ledger."),
    ("7. Data Quality", "Sales data containing missing dates, duplicate order identifiers or negative revenue must be corrected before reporting. Data owners are accountable for fixing issues within 3 business days."),
    ("8. Quota & Commission", "Regional quotas are set quarterly. Commission accelerators apply above 110% of quota; commission is withheld for deals discounted beyond policy limits until approvals are on file."),
]
styles = getSampleStyleSheet()
story = []
for head, body in POLICY:
    story.append(Paragraph(head, styles["Title" if body is None else "Heading2"]))
    if body:
        story += [Paragraph(body, styles["BodyText"]), Spacer(1, 8)]
SimpleDocTemplate(os.path.join(HERE, "company_sales_policy.pdf"), pagesize=A4, title="Company Sales Policy").build(story)
print("Generated sales_data.csv, sample_customers.csv, company_sales_policy.pdf")
