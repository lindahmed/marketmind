"""Canonical snapshots for stale-evidence checks; no raw data is sent to an agent."""
import hashlib
import json


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def metric_fingerprint(overview: dict) -> str:
    return fingerprint({"series": overview["series"], "data_quality": overview["data_quality"],
                        "reporting_period": overview["reporting_period"]})


def business_snapshot(context, currency: str) -> dict:
    return {"industry_pack": context.industry_pack.public(), "goals": list(context.goals),
            "constraints": list(context.constraints), "monthly_budget": str(context.monthly_budget), "currency": currency}
