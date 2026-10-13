"""Deterministic evaluation for explicitly simulated n8n experiment outcomes."""
import re
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy import select

from app.models import ExperimentLearning


class EvaluationAgent:
    """Compare simulation values with persisted criteria; never infer live impact."""

    name = "evaluation"
    version = "simulation-evaluation-v1"

    def evaluate(self, design: dict | None, callback_status: str, result: dict | None) -> dict:
        limitations = [
            "Values were supplied by a simulation workflow and are not real business measurements.",
            "No actual profit improvement, advertising return, causality, or statistical significance is verified.",
        ]
        if callback_status == "failed":
            return {"agent_version": self.version, "classification": "inconclusive",
                    "conclusion": "The simulation workflow reported failure; no outcome was evaluated.",
                    "simulation_only": True, "real_business_measurement": False,
                    "actual_profit_improvement_verified": False,
                    "data_quality": {"acceptable": False, "reasons": ["simulation_execution_failed"]},
                    "comparison": None, "limitations": limitations}
        if design is None:
            return {"agent_version": self.version, "classification": "inconclusive",
                    "conclusion": "No saved measurable experiment design was available for comparison.",
                    "simulation_only": True, "real_business_measurement": False,
                    "actual_profit_improvement_verified": False,
                    "data_quality": {"acceptable": False, "reasons": ["design_unavailable"]},
                    "comparison": None, "limitations": limitations}
        if result is None:
            return self._inconclusive("simulation_result_missing", limitations=limitations)

        baseline = design["baseline"]
        criteria = design["evaluation_criteria"]
        reasons = []
        try:
            start = date.fromisoformat(result["period_start"])
            end = date.fromisoformat(result["period_end"])
            calendar_days = (end - start).days + 1
        except (KeyError, TypeError, ValueError):
            calendar_days = 0
            reasons.append("reporting_period_invalid")
            start = None
        if start is not None and start <= date.fromisoformat(baseline["end"]):
            reasons.append("measurement_did_not_follow_baseline")
        if result.get("data_origin") != "simulated":
            reasons.append("data_origin_not_simulated")
        observed_days = result.get("observed_days", -1)
        if (result.get("missing_days") != 0 or observed_days < criteria["minimum_observed_days"]
                or observed_days != calendar_days):
            reasons.append("incomplete_or_short_measurement_window")
        if not result.get("financial_data_complete"):
            reasons.append("simulated_financial_cost_coverage_incomplete")
        if result.get("volume", -1) < criteria["minimum_volume"]:
            reasons.append("minimum_volume_not_met")

        metric = design["success_metrics"][0]
        values = result.get("metrics", {})
        primary_key = metric["metric"]
        profit_guardrail = criteria["profit_guardrail"]
        if primary_key not in values:
            reasons.append("primary_metric_missing")
        if profit_guardrail["metric"] not in values:
            reasons.append("profit_guardrail_metric_missing")
        if reasons:
            return self._inconclusive(*reasons, limitations=limitations,
                                      result_summary={"period_start": result.get("period_start"),
                                                      "period_end": result.get("period_end"),
                                                      "observed_days": observed_days,
                                                      "missing_days": result.get("missing_days"),
                                                      "volume": result.get("volume"),
                                                      "metrics": values})
        try:
            observed_primary = Decimal(str(values[primary_key]))
            primary_target = Decimal(metric["target"])
            observed_profit = Decimal(str(values[profit_guardrail["metric"]]))
            profit_minimum = Decimal(profit_guardrail["minimum"])
        except (InvalidOperation, TypeError, ValueError):
            return self._inconclusive("metric_value_invalid", limitations=limitations)
        if not all(value.is_finite() for value in (observed_primary, primary_target, observed_profit, profit_minimum)):
            return self._inconclusive("metric_value_invalid", limitations=limitations)
        primary_met = observed_primary >= primary_target if metric["operator"] == "gte" else observed_primary <= primary_target
        profit_met = observed_profit >= profit_minimum
        classification = "simulation_met_criteria" if primary_met and profit_met else "simulation_did_not_meet_criteria"
        return {"agent_version": self.version, "classification": classification,
                "conclusion": ("Simulated values met the configured target and profit guardrail. This is not a verified business result."
                               if primary_met and profit_met else
                               "Simulated values did not meet every configured target and profit guardrail. This is not a measured business result."),
                "simulation_only": True, "real_business_measurement": False,
                "actual_profit_improvement_verified": False,
                "data_quality": {"acceptable": True, "reasons": [],
                                  "simulated_window_days": observed_days, "simulated_volume": result["volume"],
                                  "financial_cost_coverage_reported": result["financial_data_complete"]},
                "comparison": {"primary_metric": primary_key, "baseline": baseline["primary_value"],
                               "target": str(primary_target), "simulated_value": str(observed_primary),
                               "target_met": primary_met, "profit_guardrail_baseline_per_day": profit_guardrail["minimum"],
                               "simulated_profit_per_day": str(observed_profit), "profit_guardrail_met": profit_met},
                "limitations": limitations}

    @staticmethod
    def _inconclusive(*reasons, limitations, result_summary=None):
        return {"agent_version": "simulation-evaluation-v1", "classification": "inconclusive",
                "conclusion": "The simulation did not provide sufficient comparable data for evaluation.",
                "simulation_only": True, "real_business_measurement": False,
                "actual_profit_improvement_verified": False,
                "data_quality": {"acceptable": False, "reasons": list(reasons)},
                "comparison": result_summary, "limitations": limitations}


class LearningMemoryAgent:
    """Persist deterministic, tenant-scoped experiment learning and retrieve it as labeled evidence."""

    name = "evaluation_memory"
    version = "learning-memory-v1"
    stop_words = {"about", "after", "before", "business", "could", "does", "from", "have", "into", "that", "their", "there", "this", "what", "when", "with", "would"}

    def create_learning(self, experiment, design: dict | None, callback_status: str,
                        callback_result: dict | None, evaluation: dict,
                        recommendation_id: str | None = None,
                        recommendation_approval_id: str | None = None,
                        experiment_approval_id: str | None = None) -> dict:
        design = design or {}
        return {"agent_version": self.version, "experiment_id": experiment.id,
                "hypothesis": design.get("hypothesis", experiment.name),
                "decision": {"recommendation_id": recommendation_id,
                             "recommendation_approval_id": recommendation_approval_id,
                             "recommendation_decision": "approved_for_design" if recommendation_id else "not_linked",
                             "experiment_approval_id": experiment_approval_id,
                             "experiment_decision": "approved_for_simulation" if experiment_approval_id else "unknown",
                             "experiment_status": experiment.status, "mode": "simulation_only"},
                "execution_result": {"status": callback_status, "result": callback_result},
                "conclusion": evaluation["conclusion"], "classification": evaluation["classification"],
                "evidence_ids": design.get("evidence_ids", []),
                "limitations": evaluation["limitations"], "real_business_measurement": False,
                "actual_profit_improvement_verified": False}

    def retrieve(self, db, context, question: str, limit: int = 4) -> list[dict]:
        terms = self._terms(question)
        if not terms:
            return []
        rows = db.scalars(select(ExperimentLearning).where(
            ExperimentLearning.workspace_id == context.workspace_id,
        ).order_by(ExperimentLearning.created_at.desc()).limit(200)).all()
        matches = []
        for row in rows:
            content = row.content
            searchable = " ".join([content.get("hypothesis", ""), content.get("conclusion", ""),
                                    " ".join(content.get("evidence_ids", [])),
                                    content.get("execution_result", {}).get("status", "")])
            overlap = terms & self._terms(searchable)
            if overlap:
                evidence = (f"Prior simulation learning ({content['classification']}): {content['conclusion']} "
                            "This is simulated, not a real business measurement. "
                            + " ".join(content.get("limitations", [])))
                matches.append((len(overlap), row.created_at, {
                    "kind": "prior_experiment_learning", "source_id": f"learning:{row.experiment_id}",
                    "title": f"Prior simulation: {content['hypothesis'][:140]}", "evidence": evidence,
                    "confidence": None,
                }))
        matches.sort(key=lambda item: item[1], reverse=True)
        matches.sort(key=lambda item: item[0], reverse=True)
        return [item[2] for item in matches[:limit]]

    @classmethod
    def _terms(cls, text: str) -> set[str]:
        return {word for word in re.findall(r"[a-z0-9]{3,}", text.casefold()) if word not in cls.stop_words}
