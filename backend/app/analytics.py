import io
import math
from datetime import date

import pandas as pd
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.industries import IndustryPack
from app.models import DailyMetric, Workspace

MAX_UPLOAD_BYTES = 2 * 1024 * 1024


def parse_csv(content: bytes, pack: IndustryPack) -> list[tuple[date, dict]]:
    try:
        frame = pd.read_csv(io.BytesIO(content), dtype=str, keep_default_na=False)
        if set(frame.columns) != set(pack.csv_columns):
            raise ValueError(f"Columns must be: {', '.join(pack.csv_columns)}")
        if not 1 <= len(frame) <= 10_000:
            raise ValueError("Import between 1 and 10,000 daily rows")
        days = [date.fromisoformat(value) for value in frame["date"]]
        if len(set(days)) != len(days):
            raise ValueError("Each date must appear once per file")
        records = []
        for day, row in zip(days, frame.to_dict("records"), strict=True):
            values = {key: float(row[key]) for key in pack.csv_columns if key != "date"}
            if any(not math.isfinite(value) or value < 0 or value > 1_000_000_000 for value in values.values()):
                raise ValueError("Numbers must be finite, nonnegative, and at most 1 billion")
            for key in ("orders", "bookings", "completed"):
                if key in values and not values[key].is_integer():
                    raise ValueError(f"{key} must be a whole number")
            if "completed" in values and values["completed"] > values["bookings"]:
                raise ValueError("Completed appointments cannot exceed bookings")
            records.append((day, values))
        return records
    except (ValueError, UnicodeError, pd.errors.ParserError, pd.errors.EmptyDataError) as error:
        raise HTTPException(422, str(error)) from None


def dashboard(db: Session, workspace: Workspace, pack: IndustryPack) -> dict:
    rows = db.scalars(select(DailyMetric).where(DailyMetric.workspace_id == workspace.id)
                      .order_by(DailyMetric.day)).all()
    totals = {key: sum(row.values[key] for row in rows) for key in pack.csv_columns if key != "date"}
    revenue, spend, cost = totals["revenue"], totals["ad_spend"], totals[pack.cost_column]
    profit = revenue - spend - cost
    kpis = {**totals, "estimated_profit": round(profit, 2),
            "roas": round(revenue / spend, 2) if spend else None}
    volume = totals[pack.volume_column]
    if pack.code == "ecommerce":
        kpis["average_order_value"] = round(revenue / volume, 2) if volume else None
    else:
        kpis["completion_rate"] = round(volume / totals["bookings"] * 100, 1) if totals["bookings"] else None
    findings = []
    if rows and profit < 0:
        findings.append({"code": "negative_profit", "title": "Costs exceed revenue",
                         "evidence": f"Revenue {revenue:.2f}, ad spend {spend:.2f}, variable costs {cost:.2f}.",
                         "severity": "high"})
    if pack.code == "ecommerce" and spend > 0 and revenue / spend < 1:
        findings.append({"code": "low_roas", "title": "Ad spend exceeds total revenue",
                         "evidence": f"Revenue / ad spend is {revenue / spend:.2f}.", "severity": "high"})
    if pack.code == "appointments" and totals["bookings"] and kpis["completion_rate"] < 80:
        findings.append({"code": "low_completion_rate", "title": "Appointment completion below 80%",
                         "evidence": f"{volume:.0f} completed out of {totals['bookings']:.0f} bookings.",
                         "severity": "medium"})
    # Compare consecutive seven-day calendar windows; missing days are not treated as zero.
    if len(rows) >= 14 and (rows[-1].day - rows[-14].day).days == 13:
        previous = sum(row.values["revenue"] for row in rows[-14:-7])
        recent = sum(row.values["revenue"] for row in rows[-7:])
        if previous and recent < previous * 0.8:
            findings.append({"code": "revenue_drop", "title": "Weekly revenue fell more than 20%",
                             "evidence": f"Previous 7 days: {previous:.2f}; latest 7 days: {recent:.2f}.",
                             "severity": "medium"})
    return {"business_name": workspace.name, "industry": pack.public(), "currency": workspace.currency,
            "row_count": len(rows), "period_start": rows[0].day if rows else None,
            "period_end": rows[-1].day if rows else None, "kpis": kpis, "findings": findings,
            "series": [{"date": row.day, **row.values} for row in rows],
            "profit_note": "Estimated contribution profit excludes fixed costs and taxes. ROAS uses total revenue; it is not attributed advertising revenue."}
