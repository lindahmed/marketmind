"""Shared measurable design agent. Produces drafts, never execution or claimed outcomes."""
from decimal import Decimal

from app.intelligence.growth import StrategyError

RATE_METRICS = {"unattributed_revenue_ad_spend_ratio", "average_order_value", "fulfillment_rate", "completion_rate", "refund_revenue_percentage"}


def metric_value(overview: dict, metric: str) -> Decimal:
    value = overview["kpis"].get(metric)
    if value is None:
        raise StrategyError("The selected baseline does not contain the required metric")
    amount = Decimal(str(value))
    if metric not in RATE_METRICS:
        amount /= Decimal(overview["reporting_period"]["calendar_days"])
    return amount.quantize(Decimal("0.0001"))


class ExperimentDesignAgent:
    name = "experimentation"
    version = "experiment-design-v1"

    def design(self, context, recommendation, approval, overview: dict, request) -> dict:
        if (recommendation.workspace_id != context.workspace_id or approval.workspace_id != context.workspace_id
                or approval.recommendation_id != recommendation.id or approval.recommendation_version != recommendation.version
                or recommendation.status != "approved"):
            raise PermissionError("The recommendation version has no matching owner approval")
        period = overview["reporting_period"]
        if not period["complete"] or period["calendar_days"] < 7:
            raise StrategyError("Baseline requires at least seven fully observed calendar days")
        if overview["data_quality"]["legacy_rows"]:
            raise StrategyError("A trustworthy profit guardrail requires detailed imports for every baseline day")
        volume_metric = "orders" if context.industry_pack.code == "ecommerce" else "bookings"
        minimum_volume = max(request.minimum_volume, context.industry_pack.minimum_experiment_volume)
        if overview["kpis"][volume_metric] < minimum_volume:
            raise StrategyError("Baseline has insufficient order/booking volume for this pilot")
        if request.estimated_cost > Decimal(str(context.monthly_budget)):
            raise StrategyError("Estimated experiment cost exceeds the configured monthly budget")
        item = recommendation.content
        metric = item["success_metric"]
        baseline = metric_value(overview, metric)
        target = baseline + request.minimum_change if item["direction"] == "increase" else baseline - request.minimum_change
        if metric in {"completion_rate", "fulfillment_rate"} and not 0 <= target <= 100:
            raise StrategyError("The requested target rate is outside zero to 100 percent")
        if item["direction"] == "decrease" and target < 0:
            raise StrategyError("The requested decrease would produce a negative target")
        units = ("percentage_points" if metric.endswith("rate") or metric == "refund_revenue_percentage" else
                 "ratio" if metric == "unattributed_revenue_ad_spend_ratio" else "currency_per_order" if metric == "average_order_value" else
                 "currency_per_day" if metric in {"estimated_profit", "net_revenue", "gross_revenue", "refunds"} else "count_per_day")
        return {
            "design_version": self.version, "hypothesis": item["hypothesis"], "proposed_action_type": item["action_type"],
            "action_details": item["action_details"], "evidence_ids": item["evidence_ids"],
            "measurement_method": "before_after_pilot", "currency": overview["currency"],
            "baseline": {"start": str(period["start"]), "end": str(period["end"]), "days": period["calendar_days"],
                         "primary_value": str(baseline), "volume": overview["kpis"][volume_metric],
                         "profit_per_day": str(metric_value(overview, "estimated_profit")),
                         "data_quality": overview["data_quality"]},
            "success_metrics": [{"metric": metric, "aggregation": "period_ratio" if metric in RATE_METRICS else "per_calendar_day",
                                 "units": units, "direction": item["direction"], "minimum_change": str(request.minimum_change),
                                 "target": str(target), "operator": "gte" if item["direction"] == "increase" else "lte"}],
            "estimated_cost": str(request.estimated_cost), "cost_basis": "Owner-reviewed direct cash estimate; excludes staff time. "
            "Monthly budget is a cap, not a verified remaining balance; no spend is authorized by this design.",
            "duration_days": request.duration_days,
            "evaluation_criteria": {
                "measurement_window": "Start after the baseline end and actual intervention; collect consecutive calendar days. "
                                      "Keep simulated outcomes separate from live observations.",
                "minimum_observed_days": request.duration_days, "minimum_volume": minimum_volume, "volume_metric": volume_metric,
                "profit_guardrail": {"metric": "estimated_profit", "aggregation": "per_calendar_day", "operator": "gte",
                                     "minimum": str(metric_value(overview, "estimated_profit"))},
                "success": "Primary target met AND daily contribution profit guardrail met, with complete data and minimum volume.",
                "inconclusive": "Missing dates/costs, insufficient volume, concurrent changes, or inconsistent metric definitions.",
                "failure": "With adequate comparable data, primary target or profit guardrail is not met.",
                "interpretation": "An exploratory before/after comparison cannot establish causation or statistical significance. "
                                  "A simulation cannot prove live business improvement. No outcomes have been measured.",
            },
            "constraints": list(context.constraints), "goals": list(context.goals),
            "execution_mode": "simulation_only", "status": "draft",
            "request": request.model_dump(mode="json"),
        }
