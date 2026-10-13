"""Evidence → prioritized strategy → persisted owner consent → measurable draft."""
import json
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.intelligence.growth import GrowthOutput, GrowthStrategyAgent, OpenAIGrowthProvider, StrategyError
from app.main import app
from app.models import (Experiment, ExperimentDesign, GrowthRecommendation, GrowthStrategyRun,
                        Membership, N8nDispatch, RecommendationApproval)
from tests.conftest import register
from tests.test_financial_reporting import detailed_csv
from tests.test_foundation import upload


def profile(client, **changes):
    data = client.get("/api/business").json()
    data.pop("id")
    data.pop("industry")
    data.update(changes)
    response = client.put("/api/business", json=data)
    assert response.status_code == 200, response.text


def prepare(client, industry="ecommerce", email="owner@example.com", missing_day=None, legacy=False):
    workspace = register(client, email=email, industry=industry)
    profile(client, monthly_budget="100.00", goals=["Improve profit", "Improve completion"])
    rows = []
    for i in range(14):
        if i == missing_day:
            continue
        day = date(2026, 1, 5) + timedelta(days=i)
        rows.append(f"{day},100,10,10,8,1,2,100,30,0,0,0" if industry == "ecommerce" else
                    f"{day},100,10,10,6,2,100,30,0")
    if legacy:
        content = "date,revenue,orders,ad_spend,cost_of_goods\n" + "\n".join(
            f"{date(2026, 1, 5) + timedelta(days=i)},100,10,100,30" for i in range(14))
    else:
        content = detailed_csv(*rows, industry=industry)
    assert upload(client, content).status_code == 200
    response = client.post("/api/investigations", json={"question": "What is limiting profitable growth?"})
    assert response.status_code == 201, response.text
    return workspace, response.json()


def generate(client, report):
    response = client.post(f"/api/investigations/{report['id']}/recommendations")
    assert response.status_code == 200, response.text
    return response.json()


def approve(client, row, **extra):
    return client.post(f"/api/growth/recommendations/{row['id']}/approve",
                       json={"version": row["version"], **extra})


def parameters(**changes):
    return {"baseline_start": "2026-01-05", "baseline_end": "2026-01-18", "estimated_cost": "10.00",
            "minimum_change": "5.0000", "duration_days": 14, "minimum_volume": 30, **changes}


def create_design(client, row, **changes):
    return client.post(f"/api/growth/recommendations/{row['id']}/experiment-design", json=parameters(**changes))


@pytest.mark.parametrize("industry,metric,baseline,target", [("ecommerce", "estimated_profit", "-40.0000", "-35.0000"),
                                                          ("appointments", "completion_rate", "60.0000", "65.0000")])
def test_complete_strategy_approval_design_flow_is_persisted_and_never_dispatches(clients, monkeypatch, industry, metric, baseline, target):
    first, second = clients
    workspace, report = prepare(first, industry)
    register(second, "second@example.com")
    monkeypatch.setattr("app.integrations.n8n.urllib.request.build_opener",
                        lambda *_: pytest.fail("Strategy/design must never dispatch a webhook"))
    result = generate(first, report)
    assert result["source_type"] == "industry_rule"
    row = next(item for item in result["recommendations"] if item["content"]["success_metric"] == metric)
    assert row["model"] is None and row["content"]["evidence_ids"]
    assert row["status"] == "proposed"
    assert create_design(first, row).status_code == 409
    approved = approve(first, row)
    assert approved.status_code == 200
    assert approve(first, row).json()["approval_id"] == approved.json()["approval_id"]
    design = create_design(first, row)
    assert design.status_code == 201, design.text
    saved = design.json()
    assert saved["recommendation_approval_id"] == approved.json()["approval_id"]
    assert saved["design"]["baseline"]["primary_value"] == baseline
    assert saved["design"]["success_metrics"][0]["target"] == target
    assert saved["design"]["estimated_cost"] == "10.00"
    assert saved["design"]["evaluation_criteria"]["profit_guardrail"]["minimum"] == "-40.0000"
    assert "cannot establish causation" in saved["design"]["evaluation_criteria"]["interpretation"]
    assert create_design(first, row).json()["id"] == saved["id"]
    assert create_design(first, row, minimum_change="6").status_code == 409
    assert first.get(f"/api/experiment-designs/{saved['id']}").json()["experiment_id"] == saved["experiment_id"]
    assert second.get(f"/api/experiment-designs/{saved['id']}").status_code == 404
    assert second.get("/api/experiment-designs").json() == []
    assert second.get("/api/experiments").json() == []
    listed = first.get("/api/experiments").json()
    assert len(listed) == 1 and listed[0]["id"] == saved["experiment_id"]
    assert listed[0]["status"] == "draft" and listed[0]["can_approve"] is True
    assert listed[0]["execution"] is None
    assert first.get("/api/growth/recommendations", params={"investigation_id": report["id"]}).status_code == 200
    with app.state.test_session_factory() as db:
        assert len(db.scalars(select(ExperimentDesign)).all()) == 1
        experiment = db.get(Experiment, saved["experiment_id"])
        assert experiment.workspace_id == workspace and experiment.status == "draft"
        assert experiment.action_type == "simulation_only"
        assert len(db.scalars(select(RecommendationApproval)).all()) == 1
        assert db.scalars(select(N8nDispatch)).all() == []


def test_designed_simulation_requires_separate_owner_approval_and_dispatch_is_idempotent(clients, monkeypatch):
    from app.integrations.n8n import DispatchOutcome

    owner, other = clients
    workspace, report = prepare(owner)
    register(other, "second@example.com")
    row = generate(owner, report)["recommendations"][0]
    assert approve(owner, row).status_code == 200
    designed = create_design(owner, row)
    assert designed.status_code == 201, designed.text
    experiment_id = designed.json()["experiment_id"]
    assert owner.get("/api/experiments").json()[0]["execution"] is None
    assert other.get("/api/experiments").json() == []
    assert other.post(f"/api/experiments/{experiment_id}/approve").status_code == 404

    calls = []

    class Executor:
        def execute(self, context, experiment, approval_id, version, execution_id, action_type,
                    metadata, idempotency_key, approved_at):
            calls.append((experiment, execution_id, idempotency_key))
            assert context.workspace_id == workspace
            assert action_type == "simulation_only"
            assert metadata == {"scenario": "conversion_lift"}
            return DispatchOutcome("acknowledged", 202)

    monkeypatch.setattr("app.api.configured_n8n_executor", lambda db: Executor())
    receipt = owner.post(f"/api/experiments/{experiment_id}/approve")
    assert receipt.status_code == 200, receipt.text
    assert receipt.json()["dispatch_status"] == "acknowledged"
    assert receipt.json()["completion_status"] == "not_reported"
    assert len(calls) == 1
    repeated = owner.post(f"/api/experiments/{experiment_id}/approve")
    assert repeated.status_code == 200
    assert repeated.json()["execution_id"] == receipt.json()["execution_id"]
    assert len(calls) == 1
    status = owner.get("/api/experiments").json()[0]
    assert status["status"] == "approved"
    assert status["execution"]["status"] == "acknowledged"
    assert status["execution"]["execution_id"] == receipt.json()["execution_id"]
    assert status["execution"]["completion_status"] == "not_reported"


def test_changed_budget_blocks_designed_simulation_before_owner_dispatch(clients, monkeypatch):
    owner, _ = clients
    prepare(owner)
    report = owner.get("/api/investigations").json()[0]
    row = generate(owner, report)["recommendations"][0]
    assert approve(owner, row).status_code == 200
    designed = create_design(owner, row)
    assert designed.status_code == 201
    experiment_id = designed.json()["experiment_id"]
    profile(owner, monthly_budget="5.00")
    monkeypatch.setattr("app.api.configured_n8n_executor",
                        lambda db: pytest.fail("A stale design must not reach n8n"))
    blocked = owner.post(f"/api/experiments/{experiment_id}/approve")
    assert blocked.status_code == 409
    with app.state.test_session_factory() as db:
        experiment = db.get(Experiment, experiment_id)
        assert experiment.status == "draft"
        assert db.scalars(select(N8nDispatch).where(N8nDispatch.experiment_id == experiment_id)).all() == []


def test_generation_is_idempotent_and_goal_alignment_prioritizes(clients):
    client, _ = clients
    _, report = prepare(client)
    profile(client, goals=["Improve marketing efficiency"])
    generated = generate(client, report)
    assert generated["recommendations"][0]["content"]["action_type"] == "audience"
    assert generated["recommendations"][0]["content"]["goal_links"] == ["Improve marketing efficiency"]
    assert generate(client, report)["strategy_run_id"] == generated["strategy_run_id"]
    with app.state.test_session_factory() as db:
        assert len(db.scalars(select(GrowthStrategyRun)).all()) == 1
        assert len(db.scalars(select(GrowthRecommendation)).all()) == 2


def test_constraints_filter_actions_and_require_owner_review(clients):
    client, _ = clients
    _, report = prepare(client)
    profile(client, constraints=["No audience changes", "Use an accessible checkout"])
    rows = generate(client, report)["recommendations"]
    assert [row["content"]["action_type"] for row in rows] == ["checkout"]
    assert approve(client, rows[0]).status_code == 422
    assert approve(client, rows[0], constraints_acknowledged=True).status_code == 200
    profile(client, constraints=["No experiments"])
    assert generate(client, report)["recommendations"] == []


def test_no_supporting_rule_returns_empty_strategy_not_invented_results(clients):
    client, _ = clients
    register(client)
    assert upload(client, detailed_csv("2026-01-05,1000,0,10,10,0,0,10,10,0,0,0")).status_code == 200
    report = client.post("/api/investigations", json={"question": "What should improve?"}).json()
    assert generate(client, report)["recommendations"] == []


def test_cross_tenant_and_non_owner_approvals_are_denied(clients):
    first, second = clients
    workspace, report = prepare(first)
    other_workspace = register(second, "second@example.com")
    row = generate(first, report)["recommendations"][0]
    assert second.post(f"/api/investigations/{report['id']}/recommendations").status_code == 404
    assert approve(second, row).status_code == 404
    assert create_design(second, row).status_code == 404
    assert second.get("/api/growth/recommendations", params={"investigation_id": report["id"]}).status_code == 404
    assert second.post(f"/api/investigations/{report['id']}/recommendations", headers={"X-Workspace-ID": workspace}).status_code == 403
    with app.state.test_session_factory() as db:
        member = db.scalar(select(Membership).where(Membership.workspace_id == other_workspace))
        member.workspace_id = workspace
        member.role = "member"
        db.commit()
    assert approve(second, row).status_code == 403
    assert create_design(second, row).status_code == 403


def test_exact_version_rejection_and_revoked_approver_role(clients):
    client, _ = clients
    workspace, report = prepare(client)
    rows = generate(client, report)["recommendations"]
    assert client.post(f"/api/growth/recommendations/{rows[0]['id']}/approve", json={"version": 2}).status_code == 409
    rejected = client.post(f"/api/growth/recommendations/{rows[0]['id']}/reject", json={"version": 1})
    assert rejected.json()["status"] == "rejected"
    assert approve(client, rows[0]).status_code == 409
    assert create_design(client, rows[0]).status_code == 409
    assert approve(client, rows[1]).status_code == 200
    with app.state.test_session_factory() as db:
        db.scalar(select(Membership).where(Membership.workspace_id == workspace)).role = "member"
        db.commit()
    assert create_design(client, rows[1]).status_code == 403


@pytest.mark.parametrize("change", [{"monthly_budget": "5"}, {"goals": ["New goal"]}, {"constraints": ["No checkout changes"]}])
def test_changed_business_context_invalidates_approval_and_design(clients, change):
    client, _ = clients
    _, report = prepare(client)
    row = generate(client, report)["recommendations"][0]
    assert approve(client, row).status_code == 200
    profile(client, **change)
    assert approve(client, row).status_code == 409
    assert create_design(client, row).status_code == 409


def test_reimported_financial_evidence_invalidates_strategy_and_design(clients):
    client, _ = clients
    _, report = prepare(client)
    row = generate(client, report)["recommendations"][0]
    assert approve(client, row).status_code == 200
    assert upload(client, detailed_csv("2026-01-05,999,10,10,8,1,2,100,30,0,0,0")).status_code == 200
    assert client.post(f"/api/investigations/{report['id']}/recommendations").status_code == 409
    assert create_design(client, row).status_code == 409


def test_deleted_cited_document_requires_fresh_investigation(clients):
    client, _ = clients
    _, _ = prepare(client)
    document = client.post("/api/knowledge/documents", files={"file": ("growth.md", b"Profit growth is limited by shipping costs.", "text/markdown")})
    assert document.status_code == 201
    report = client.post("/api/investigations", json={"question": "Why is profit growth limited?"}).json()
    assert report["result"]["evidence_sources"]
    row = generate(client, report)["recommendations"][0]
    assert approve(client, row).status_code == 200
    assert client.delete(f"/api/knowledge/documents/{document.json()['id']}").status_code == 204
    assert create_design(client, row).status_code == 409


def test_zero_budget_allows_review_drafts_but_not_paid_designs(clients):
    client, _ = clients
    _, report = prepare(client)
    profile(client, monthly_budget="0.00")
    row = generate(client, report)["recommendations"][0]
    assert approve(client, row).status_code == 200
    assert create_design(client, row).status_code == 422
    assert create_design(client, row, estimated_cost="0.00").status_code == 201


@pytest.mark.parametrize("setup,params", [({"missing_day": 5}, {}), ({"legacy": True}, {}), ({}, {"estimated_cost": "101"}),
                                         ({}, {"minimum_volume": 1000}), ({}, {"baseline_start": "2025-12-01", "baseline_end": "2025-12-14"})])
def test_untrustworthy_or_unaffordable_baselines_are_rejected(clients, setup, params):
    client, _ = clients
    _, report = prepare(client, **setup)
    row = generate(client, report)["recommendations"][0]
    assert approve(client, row).status_code == 200
    response = create_design(client, row, **params)
    assert response.status_code == 422, response.text
    assert client.get("/api/experiment-designs").json() == []


def test_rate_target_must_be_possible(clients):
    client, _ = clients
    _, report = prepare(client, "appointments")
    row = next(item for item in generate(client, report)["recommendations"] if item["content"]["success_metric"] == "completion_rate")
    assert approve(client, row).status_code == 200
    assert create_design(client, row, minimum_change="50").status_code == 422


def candidate(**changes):
    return {"key": "margin_review", "title": "Review margin", "rationale": "Imported costs exceed net revenue.",
            "action_type": "checkout", "action_details": "Test clearer checkout delivery information.",
            "hypothesis": "Clearer information may improve contribution profit.", "success_metric": "estimated_profit",
            "direction": "increase", "evidence_ids": ["negative_profit"], "goal_links": ["Improve profit"],
            "estimated_cost": 10, "cost_basis": "Unverified direct cash estimate; excludes staff time.", **changes}


class Provider:
    model_id = "test:structured-growth"

    def __init__(self, changes=None):
        self.changes = changes or {}

    def recommend(self, context, evidence):
        assert context["industry_pack"]["code"] == "ecommerce"
        return GrowthOutput.model_validate({"recommendations": [candidate(**self.changes)]}), {
            "input_tokens": 10, "output_tokens": 20, "estimated_cost_usd": None, "cost_schedule": None,
        }


def analyzed_run(report):
    from app.models import InvestigationRun
    evidence = dict(report["result"])
    evidence["assessment_source_ids"] = ["negative_profit"]
    evidence["analysis_findings"] = [{"title": "Margin pressure", "evidence": "Imported costs exceed revenue.",
                                     "source_ids": ["negative_profit"]}]
    return InvestigationRun(workspace_id="tenant-a", status="analyzed", result=evidence)


def test_provider_strategy_uses_cited_analysis_and_records_real_provider_metadata(clients):
    from app.intelligence.contracts import BusinessContext
    from app.industries import PACKS
    client, _ = clients
    _, report = prepare(client)
    context = BusinessContext("tenant-a", PACKS["ecommerce"], ("Improve profit",), (), 100)
    result = GrowthStrategyAgent(Provider()).recommend(context, analyzed_run(report))
    assert result["source_type"] == "provider" and result["model"] == Provider.model_id
    assert result["input_tokens"] == 10 and result["recommendations"][0]["estimated_cost"] == "10"
    with pytest.raises(StrategyError, match="analyzed"):
        run = analyzed_run(report)
        run.status = "evidence_ready"
        GrowthStrategyAgent(Provider()).recommend(context, run)


@pytest.mark.parametrize("changes", [{"evidence_ids": ["foreign-secret"]}, {"evidence_ids": ["low_unattributed_revenue_ad_spend_ratio"]},
                                     {"action_type": "unregistered"}, {"success_metric": "fake_conversion"},
                                     {"goal_links": ["Invented goal"]}, {"direction": "decrease"}])
def test_provider_output_cannot_forge_sources_actions_metrics_or_goals(clients, changes):
    from app.intelligence.contracts import BusinessContext
    from app.industries import PACKS
    client, _ = clients
    _, report = prepare(client)
    context = BusinessContext("tenant-a", PACKS["ecommerce"], ("Improve profit",), (), 100)
    with pytest.raises(StrategyError):
        GrowthStrategyAgent(Provider(changes)).recommend(context, analyzed_run(report))
    assert GrowthStrategyAgent(Provider({"estimated_cost": 101})).recommend(context, analyzed_run(report))["recommendations"] == []


def test_openai_growth_reuses_bounded_structured_transport_and_usage(monkeypatch):
    payload = {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text",
               "text": json.dumps({"recommendations": [candidate()]})}]}],
               "usage": {"input_tokens": 100, "output_tokens": 200}}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def read(self, _):
            return json.dumps(payload).encode()

    class Opener:
        def open(self, request, timeout):
            body = json.loads(request.data)
            assert body["store"] is False and body["text"]["format"]["strict"] is True
            assert body["text"]["format"]["name"] == "marketmind_growth"
            assert timeout == 7
            return Response()

    monkeypatch.setattr("app.intelligence.investigation.urllib.request.build_opener", lambda *_: Opener())
    result, usage = OpenAIGrowthProvider("test-only-secret", "gpt-4o-mini", 7).recommend({}, {"cited": "negative_profit"})
    assert result.recommendations[0].evidence_ids == ["negative_profit"]
    assert usage["input_tokens"] == 100 and usage["estimated_cost_usd"] is not None
