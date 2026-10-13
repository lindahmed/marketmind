from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor

from tests.conftest import register
from tests.test_foundation import upload


def create_source(client, workspace_id, identifier, name="Sheet"):
    response = client.post("/api/data-sources", headers={"X-Workspace-ID": workspace_id},
                           json={"name": name, "provider": "google_sheets", "source_identifier": identifier})
    assert response.status_code == 201, response.text
    return response.json()


def batch(records, request_id="request-0001"):
    return {"request_id": request_id, "records": records}


def complete_financial_coverage():
    return {"coverage": [{"day": "2026-06-01", "data_kind": kind, "complete": True}
                         for kind in ("payments", "refunds", "marketing_spend", "variable_costs", "fixed_costs")]}


def ecom_records(payment_amount="100.00"):
    happened = datetime(2026, 6, 1, 12, tzinfo=timezone.utc).isoformat()
    return [
        {"source_event_id": "row-order", "event_type": "order", "occurred_at": happened,
         "entity_id": "order-42", "amount": "100.00", "currency": "USD", "record_locator": "Orders!A2"},
        {"source_event_id": "row-payment", "event_type": "payment", "occurred_at": happened,
         "entity_id": "order-42", "amount": payment_amount, "currency": "USD", "status": "captured",
         "campaign_id": "spring-sale"},
        {"source_event_id": "row-fulfillment", "event_type": "fulfillment", "occurred_at": happened,
         "entity_id": "order-42", "status": "fulfilled"},
        {"source_event_id": "row-spend", "event_type": "marketing_spend", "occurred_at": happened,
         "entity_id": "campaign-day-1", "amount": "20.00", "currency": "USD", "campaign_id": "spring-sale"},
        {"source_event_id": "row-variable", "event_type": "expense", "occurred_at": happened,
         "entity_id": "cogs-order-42", "amount": "30.00", "currency": "USD", "cost_category": "variable"},
        {"source_event_id": "row-fixed", "event_type": "expense", "occurred_at": happened,
         "entity_id": "rent-day-1", "amount": "10.00", "currency": "USD", "cost_category": "fixed"},
    ]


def test_owner_managed_sheets_source_secure_ingestion_and_reconciled_analytics(clients):
    owner, other = clients
    workspace_id = register(owner)
    foreign_workspace = register(other, "another@example.com")
    source = create_source(owner, workspace_id, "sheet-abc")
    token = source["ingestion_token"]
    source_id = source["id"]
    assert "secret_hash" not in owner.get("/api/data-sources", headers={"X-Workspace-ID": workspace_id}).text
    foreign_source = create_source(other, foreign_workspace, "other-sheet")
    unauthorized = other.post(f"/api/integrations/google-sheets/{source_id}/ingest", json=batch(ecom_records()),
                              headers={"Authorization": f"Bearer {foreign_source['ingestion_token']}"})
    assert unauthorized.status_code == 401
    assert other.get("/api/data-sources/quality", headers={"X-Workspace-ID": workspace_id}).status_code == 403
    assert owner.post(f"/api/integrations/google-sheets/{source_id}/ingest", json=batch(ecom_records())).status_code == 401

    first_batch = {**batch(ecom_records()), **complete_financial_coverage()}
    imported = owner.post(f"/api/integrations/google-sheets/{source_id}/ingest", json=first_batch,
                          headers={"Authorization": f"Bearer {token}"})
    assert imported.status_code == 200, imported.text
    result = imported.json()
    assert (result["received_count"], result["accepted_count"], result["conflict_count"]) == (6, 6, 0)
    replay = owner.post(f"/api/integrations/google-sheets/{source_id}/ingest", json=first_batch,
                        headers={"Authorization": f"Bearer {token}"})
    assert replay.status_code == 200 and replay.json()["replayed"] is True
    changed_replay = owner.post(f"/api/integrations/google-sheets/{source_id}/ingest",
                                json={**batch(ecom_records("101.00")), **complete_financial_coverage()},
                                headers={"Authorization": f"Bearer {token}"})
    assert changed_replay.status_code == 409

    second = create_source(owner, workspace_id, "sheet-secondary", "Secondary sheet")
    second_batch = [dict(row, source_event_id=f"secondary-{row['source_event_id']}",
                         record_locator="Copy!A1") for row in ecom_records("101.00")]
    reconciled = owner.post(f"/api/integrations/google-sheets/{second['id']}/ingest",
                            json={**batch(second_batch, "request-0002"), **complete_financial_coverage()},
                            headers={"Authorization": f"Bearer {second['ingestion_token']}"})
    assert reconciled.status_code == 200, reconciled.text
    summary = reconciled.json()
    assert summary["duplicate_count"] == 5
    assert summary["conflict_count"] == 1

    dashboard = owner.get("/api/dashboard", headers={"X-Workspace-ID": workspace_id}).json()
    assert dashboard["kpis"]["net_revenue"] is None
    assert dashboard["kpis"]["estimated_profit"] is None
    assert dashboard["kpis"]["estimated_operating_profit"] is None
    assert dashboard["kpis"]["fulfillment_rate"] == 100
    assert dashboard["source_metrics"]["recorded_campaign_payments"] == {"spring-sale": 100}
    assert "causality" in dashboard["source_metrics"]["campaign_interpretation"]

    quality = owner.get("/api/data-sources/quality", headers={"X-Workspace-ID": workspace_id}).json()
    assert quality["source_count"] == 2
    assert quality["reconciliation"]["duplicate_events"] == 5
    assert quality["reconciliation"]["conflicting_events"] == 1
    assert any(row["status"] == "conflict" and row["matched_event_id"] for row in quality["conflicts"])
    assert owner.post(f"/api/data-sources/{source_id}/revoke",
                      headers={"X-Workspace-ID": workspace_id}).status_code == 204
    assert owner.post(f"/api/integrations/google-sheets/{source_id}/ingest", json=batch(ecom_records()),
                      headers={"Authorization": f"Bearer {token}"}).status_code == 401
    replacement = owner.post(f"/api/data-sources/{source_id}/rotate-token",
                             headers={"X-Workspace-ID": workspace_id})
    assert replacement.status_code == 200
    new_token = replacement.json()["ingestion_token"]
    assert owner.post(f"/api/integrations/google-sheets/{source_id}/ingest", json=batch(ecom_records()),
                      headers={"Authorization": f"Bearer {token}"}).status_code == 401
    assert owner.post(f"/api/integrations/google-sheets/{source_id}/ingest", json=first_batch,
                      headers={"Authorization": f"Bearer {new_token}"}).json()["replayed"] is True
    assert foreign_workspace != workspace_id


def test_missing_required_fields_are_retained_and_excluded_from_reconciled_metrics(clients):
    client, _ = clients
    workspace_id = register(client)
    source = create_source(client, workspace_id, "sheet-missing")
    event = {"source_event_id": "payment-missing-amount", "event_type": "payment",
             "occurred_at": "2026-06-02T10:00:00Z", "entity_id": "order-missing", "status": "captured"}
    response = client.post(f"/api/integrations/google-sheets/{source['id']}/ingest",
                           json=batch([event]), headers={"Authorization": f"Bearer {source['ingestion_token']}"})
    assert response.status_code == 200
    assert response.json()["missing_count"] == 1
    quality = client.get("/api/data-sources/quality", headers={"X-Workspace-ID": workspace_id}).json()
    assert quality["conflicts"][0]["status"] == "missing"
    assert quality["conflicts"][0]["note"] == "missing_required_fields:amount,currency"
    dashboard = client.get("/api/dashboard", headers={"X-Workspace-ID": workspace_id}).json()
    assert dashboard["kpis"]["net_revenue"] is None
    assert dashboard["source_metrics"]["financial_completeness"]["contribution_complete"] is False


def test_appointment_event_rollup_uses_industry_specific_outcomes(clients):
    client, _ = clients
    workspace_id = register(client, industry="appointments")
    source = create_source(client, workspace_id, "sheet-appointments")
    time = "2026-06-03T10:00:00Z"
    events = [{"source_event_id": f"booking-{status}", "event_type": "appointment_outcome",
               "occurred_at": time, "entity_id": f"booking-{index}", "status": status}
              for index, status in enumerate(("completed", "cancelled", "no_show", "booked"))]
    events += [{"source_event_id": "pay-1", "event_type": "payment", "occurred_at": time,
                "entity_id": "booking-0", "amount": "80", "currency": "USD", "status": "captured"}]
    response = client.post(f"/api/integrations/google-sheets/{source['id']}/ingest",
                           json=batch(events), headers={"Authorization": f"Bearer {source['ingestion_token']}"})
    assert response.status_code == 200
    dashboard = client.get("/api/dashboard", headers={"X-Workspace-ID": workspace_id}).json()
    assert dashboard["kpis"]["bookings"] == 4
    assert dashboard["kpis"]["completed"] == 1
    assert dashboard["kpis"]["cancelled"] == 1
    assert dashboard["kpis"]["completion_rate"] == 25


def test_reconciled_partial_event_day_does_not_replace_existing_csv_summary(clients):
    client, _ = clients
    workspace_id = register(client)
    assert upload(client, "date,revenue,orders,ad_spend,cost_of_goods\n2026-06-01,500,5,50,200\n").status_code == 200
    source = create_source(client, workspace_id, "sheet-overlap")
    response = client.post(f"/api/integrations/google-sheets/{source['id']}/ingest",
                           json=batch(ecom_records()), headers={"Authorization": f"Bearer {source['ingestion_token']}"})
    assert response.status_code == 200
    dashboard = client.get("/api/dashboard", headers={"X-Workspace-ID": workspace_id}).json()
    assert dashboard["kpis"]["gross_revenue"] == 500
    assert dashboard["kpis"]["orders"] == 5
    assert dashboard["data_quality"]["source_overlap_days"] == 1
    assert dashboard["source_metrics"]["csv_overlap_dates"] == ["2026-06-01"]


def test_data_source_owner_access_and_provider_validation(clients):
    client, _ = clients
    workspace_id = register(client)
    with client.app.state.test_session_factory() as db:
        from sqlalchemy import select
        from app.models import Membership
        membership = db.scalar(select(Membership).where(Membership.workspace_id == workspace_id))
        membership.role = "analyst"
        db.commit()
    assert client.post("/api/data-sources", headers={"X-Workspace-ID": workspace_id},
                       json={"name": "Sheet", "provider": "google_sheets", "source_identifier": "abc"}).status_code == 403
    assert client.post("/api/data-sources", headers={"X-Workspace-ID": workspace_id},
                       json={"name": "Sheet", "provider": "csv", "source_identifier": "abc"}).status_code == 422


def test_updated_appointment_replaces_current_state_and_retains_raw_history(clients):
    client, _ = clients
    workspace_id = register(client, industry="appointments")
    source = create_source(client, workspace_id, "appointments-updates")
    headers = {"Authorization": f"Bearer {source['ingestion_token']}"}
    url = f"/api/integrations/google-sheets/{source['id']}/ingest"
    original = {"source_event_id": "booking-row-1", "event_type": "appointment_outcome",
                "occurred_at": "2026-06-03T10:00:00Z", "entity_id": "booking-1", "status": "booked"}
    assert client.post(url, json=batch([original]), headers=headers).status_code == 200
    updated = {**original, "occurred_at": "2026-06-04T10:00:00Z", "status": "completed"}
    assert client.post(url, json=batch([updated], "request-0002"), headers=headers).status_code == 200
    dashboard = client.get("/api/dashboard", headers={"X-Workspace-ID": workspace_id}).json()
    assert dashboard["kpis"]["bookings"] == 1
    assert dashboard["kpis"]["completed"] == 1
    with client.app.state.test_session_factory() as db:
        from sqlalchemy import select
        from app.models import BusinessEvent
        rows = db.scalars(select(BusinessEvent).where(BusinessEvent.entity_id == "booking-1")).all()
        assert len(rows) == 2
        assert sum(row.is_current for row in rows) == 1


def test_appointment_metrics_use_booking_scheduled_and_completion_dates(clients):
    client, _ = clients
    workspace_id = register(client, industry="appointments")
    source = create_source(client, workspace_id, "appointment-dates")
    event = {"source_event_id": "booking-row-dates", "event_type": "appointment_outcome",
             "occurred_at": "2026-06-05T15:00:00Z", "entity_id": "booking-dates", "status": "completed",
             "booked_at": "2026-06-01T09:00:00Z", "scheduled_at": "2026-06-03T10:00:00Z",
             "completed_at": "2026-06-05T14:30:00Z"}
    response = client.post(f"/api/integrations/google-sheets/{source['id']}/ingest", json=batch([event]),
                           headers={"Authorization": f"Bearer {source['ingestion_token']}"})
    assert response.status_code == 200, response.text
    headers = {"X-Workspace-ID": workspace_id}
    dashboard = client.get("/api/dashboard", headers=headers).json()
    assert (dashboard["kpis"]["bookings"], dashboard["kpis"]["scheduled_appointments"],
            dashboard["kpis"]["completed"], dashboard["kpis"]["completion_rate"]) == (1, 1, 1, 100)
    booking_day = client.get("/api/dashboard?start_date=2026-06-01&end_date=2026-06-01",
                             headers=headers).json()
    scheduled_day = client.get("/api/dashboard?start_date=2026-06-03&end_date=2026-06-03",
                               headers=headers).json()
    completion_day = client.get("/api/dashboard?start_date=2026-06-05&end_date=2026-06-05",
                                headers=headers).json()
    assert (booking_day["kpis"]["bookings"], booking_day["kpis"]["completed"]) == (1, 0)
    assert scheduled_day["kpis"]["scheduled_appointments"] == 1
    assert (completion_day["kpis"]["bookings"], completion_day["kpis"]["completed"]) == (0, 1)


def test_partial_payments_refunds_and_source_deletion_preserve_history(clients):
    client, _ = clients
    workspace_id = register(client)
    source = create_source(client, workspace_id, "transactions")
    headers = {"Authorization": f"Bearer {source['ingestion_token']}"}
    url = f"/api/integrations/google-sheets/{source['id']}/ingest"
    records = [
        {"source_event_id": "pay-a", "event_type": "payment", "occurred_at": "2026-06-01T10:00:00Z",
         "entity_id": "payment-a", "amount": "60", "currency": "USD", "status": "captured"},
        {"source_event_id": "pay-b", "event_type": "payment", "occurred_at": "2026-06-01T11:00:00Z",
         "entity_id": "payment-b", "amount": "40", "currency": "USD", "status": "captured"},
        {"source_event_id": "refund-a", "event_type": "refund", "occurred_at": "2026-06-01T12:00:00Z",
         "entity_id": "refund-a", "amount": "10", "currency": "USD"},
    ]
    coverage = {"coverage": [{"day": "2026-06-01", "data_kind": kind, "complete": True}
                             for kind in ("payments", "refunds", "marketing_spend", "variable_costs", "fixed_costs")]}
    assert client.post(url, json={**batch(records), **coverage}, headers=headers).status_code == 200
    repeated = client.post(url, json=batch([records[0]], "request-repeat"), headers=headers)
    assert repeated.status_code == 200 and repeated.json()["duplicate_count"] == 1
    first = client.get("/api/dashboard", headers={"X-Workspace-ID": workspace_id}).json()
    assert first["kpis"]["gross_revenue"] == 100
    assert first["kpis"]["refunds"] == 10
    corrected = {**records[0], "amount": "50"}
    assert client.post(url, json=batch([corrected], "request-correction"), headers=headers).status_code == 200
    current = client.get("/api/dashboard", headers={"X-Workspace-ID": workspace_id}).json()
    assert current["kpis"]["gross_revenue"] == 90
    assert current["kpis"]["net_revenue"] == 80
    deleted = client.post(url, json={"request_id": "request-delete", "deleted_source_event_ids": ["refund-a"]},
                          headers=headers)
    assert deleted.status_code == 200 and deleted.json()["deleted_count"] == 1
    final = client.get("/api/dashboard", headers={"X-Workspace-ID": workspace_id}).json()
    assert final["kpis"]["refunds"] == 0
    with client.app.state.test_session_factory() as db:
        from sqlalchemy import select
        from app.models import BusinessEvent
        refund_history = db.scalars(select(BusinessEvent).where(BusinessEvent.source_event_id == "refund-a")).all()
        assert len(refund_history) == 2
        assert {row.reconciliation_status for row in refund_history} == {"accepted", "deleted"}
        assert {row.is_current for row in refund_history} == {False}


def test_incomplete_financial_coverage_is_unknown_but_explicit_zero_cost_is_complete(clients):
    client, _ = clients
    workspace_id = register(client)
    source = create_source(client, workspace_id, "coverage")
    headers = {"Authorization": f"Bearer {source['ingestion_token']}"}
    url = f"/api/integrations/google-sheets/{source['id']}/ingest"
    payment = {"source_event_id": "pay-1", "event_type": "payment", "occurred_at": "2026-06-01T10:00:00Z",
               "entity_id": "payment-1", "amount": "100", "currency": "USD", "status": "captured"}
    assert client.post(url, json=batch([payment]), headers=headers).status_code == 200
    assert client.get("/api/dashboard", headers={"X-Workspace-ID": workspace_id}).json()["kpis"]["estimated_profit"] is None
    coverage = {"coverage": [{"day": "2026-06-01", "data_kind": kind, "complete": True}
                             for kind in ("payments", "refunds", "marketing_spend", "variable_costs", "fixed_costs")]}
    response = client.post(url, json={**batch([], "coverage-zero"), **coverage}, headers=headers)
    assert response.status_code == 200, response.text
    report = client.get("/api/dashboard", headers={"X-Workspace-ID": workspace_id}).json()
    assert report["kpis"]["estimated_profit"] == 100
    assert report["kpis"]["estimated_operating_profit"] == 100
    assert report["source_metrics"]["financial_completeness"]["complete"] is True


def test_complete_coverage_only_day_is_a_legitimate_zero_activity_day(clients):
    client, _ = clients
    workspace_id = register(client)
    source = create_source(client, workspace_id, "zero-activity-day")
    coverage = {"coverage": [{"day": "2026-06-02", "data_kind": kind, "complete": True}
                             for kind in ("payments", "refunds", "marketing_spend", "variable_costs", "fixed_costs")]}
    response = client.post(f"/api/integrations/google-sheets/{source['id']}/ingest",
        json={"request_id": "coverage-only-1", "records": [], **coverage},
        headers={"Authorization": f"Bearer {source['ingestion_token']}"})
    assert response.status_code == 200, response.text
    dashboard = client.get("/api/dashboard", headers={"X-Workspace-ID": workspace_id}).json()
    assert dashboard["row_count"] == 1
    assert dashboard["kpis"]["estimated_profit"] == 0
    assert dashboard["kpis"]["estimated_operating_profit"] == 0


def test_partial_or_conflicting_source_coverage_withholds_profit(clients):
    client, _ = clients
    workspace_id = register(client)
    first = create_source(client, workspace_id, "coverage-complete")
    second = create_source(client, workspace_id, "coverage-partial")
    headers_a = {"Authorization": f"Bearer {first['ingestion_token']}"}
    headers_b = {"Authorization": f"Bearer {second['ingestion_token']}"}
    first_event = {"source_event_id": "pay-a", "event_type": "payment", "occurred_at": "2026-06-01T10:00:00Z",
                   "entity_id": "payment-a", "amount": "100", "currency": "USD", "status": "captured"}
    complete = {"coverage": [{"day": "2026-06-01", "data_kind": kind, "complete": True}
                              for kind in ("payments", "refunds", "marketing_spend", "variable_costs", "fixed_costs")]}
    client.post(f"/api/integrations/google-sheets/{first['id']}/ingest",
        json={**batch([first_event]), **complete}, headers=headers_a)
    second_event = {"source_event_id": "pay-b", "event_type": "payment", "occurred_at": "2026-06-01T11:00:00Z",
                    "entity_id": "payment-b", "amount": "30", "currency": "USD", "status": "captured"}
    partial = client.post(f"/api/integrations/google-sheets/{second['id']}/ingest",
        json=batch([second_event], "partial-source-1"), headers=headers_b)
    assert partial.status_code == 200
    dashboard = client.get("/api/dashboard", headers={"X-Workspace-ID": workspace_id}).json()
    assert dashboard["kpis"]["estimated_profit"] is None
    conflicting_coverage = {"coverage": [{"day": "2026-06-01", "data_kind": kind,
                                          "complete": kind != "payments"}
                                         for kind in ("payments", "refunds", "marketing_spend",
                                                      "variable_costs", "fixed_costs")]}
    revised_coverage = client.post(f"/api/integrations/google-sheets/{second['id']}/ingest",
        json={"request_id": "coverage-conflict-1", "records": [], **conflicting_coverage}, headers=headers_b)
    assert revised_coverage.status_code == 200
    assert client.get("/api/dashboard", headers={"X-Workspace-ID": workspace_id}).json()["kpis"]["estimated_profit"] is None

    conflict_source = create_source(client, workspace_id, "coverage-conflict")
    conflicting = {**first_event, "source_event_id": "pay-a-copy", "amount": "125"}
    conflict = client.post(f"/api/integrations/google-sheets/{conflict_source['id']}/ingest",
        json={**batch([conflicting], "conflict-source-1"), **complete},
        headers={"Authorization": f"Bearer {conflict_source['ingestion_token']}"})
    assert conflict.status_code == 200 and conflict.json()["conflict_count"] == 1
    after_conflict = client.get("/api/dashboard", headers={"X-Workspace-ID": workspace_id}).json()
    assert after_conflict["kpis"]["estimated_profit"] is None


def test_conflict_resolution_is_owner_scoped_and_audited(clients):
    owner, other = clients
    workspace_id = register(owner)
    source_a = create_source(owner, workspace_id, "conflict-a")
    source_b = create_source(owner, workspace_id, "conflict-b")
    event = {"source_event_id": "order-1", "event_type": "order", "occurred_at": "2026-06-01T10:00:00Z",
             "entity_id": "order-1", "amount": "100", "currency": "USD"}
    owner.post(f"/api/integrations/google-sheets/{source_a['id']}/ingest", json=batch([event]),
               headers={"Authorization": f"Bearer {source_a['ingestion_token']}"})
    changed = {**event, "source_event_id": "order-copy", "amount": "120"}
    owner.post(f"/api/integrations/google-sheets/{source_b['id']}/ingest", json=batch([changed], "request-0002"),
               headers={"Authorization": f"Bearer {source_b['ingestion_token']}"})
    quality = owner.get("/api/data-sources/quality", headers={"X-Workspace-ID": workspace_id}).json()
    conflict = next(row for row in quality["conflicts"] if row["status"] == "conflict")
    foreign_workspace = register(other, "foreign-owner@example.com")
    assert other.post(f"/api/data-sources/conflicts/{conflict['id']}/resolve",
                      headers={"X-Workspace-ID": foreign_workspace},
                      json={"decision": "accept_incoming"}).status_code == 404
    resolved = owner.post(f"/api/data-sources/conflicts/{conflict['id']}/resolve",
                          headers={"X-Workspace-ID": workspace_id},
                          json={"decision": "accept_incoming", "note": "Verified against signed ledger"})
    assert resolved.status_code == 200, resolved.text
    repeated = owner.post(f"/api/data-sources/conflicts/{conflict['id']}/resolve",
                          headers={"X-Workspace-ID": workspace_id},
                          json={"decision": "accept_incoming", "note": "repeat"})
    assert repeated.status_code == 200 and repeated.json()["replayed"] is True
    contradictory = owner.post(f"/api/data-sources/conflicts/{conflict['id']}/resolve",
                               headers={"X-Workspace-ID": workspace_id},
                               json={"decision": "retain_existing"})
    assert contradictory.status_code == 409
    assert len(owner.get("/api/data-sources/quality", headers={"X-Workspace-ID": workspace_id}).json()["decisions"]) == 1
    report = owner.get("/api/dashboard", headers={"X-Workspace-ID": workspace_id}).json()
    assert report["kpis"]["orders"] == 1


def test_competing_conflicts_resolve_against_the_latest_current_record(clients):
    owner, _ = clients
    workspace_id = register(owner)
    sources = [create_source(owner, workspace_id, f"competing-{index}") for index in range(3)]
    base = {"source_event_id": "order-base", "event_type": "order", "occurred_at": "2026-06-01T10:00:00Z",
            "entity_id": "order-shared", "amount": "100", "currency": "USD"}
    changed1 = {**base, "source_event_id": "order-one", "amount": "110"}
    changed2 = {**base, "source_event_id": "order-two", "amount": "120"}
    for index, record in enumerate((base, changed1, changed2)):
        response = owner.post(f"/api/integrations/google-sheets/{sources[index]['id']}/ingest",
            json=batch([record], f"competing-request-{index}"),
            headers={"Authorization": f"Bearer {sources[index]['ingestion_token']}"})
        assert response.status_code == 200, response.text
    quality = owner.get("/api/data-sources/quality", headers={"X-Workspace-ID": workspace_id}).json()
    conflicts = {row["source_event_id"]: row for row in quality["conflicts"] if row["status"] == "conflict"}
    first = owner.post(f"/api/data-sources/conflicts/{conflicts['order-one']['id']}/resolve",
        headers={"X-Workspace-ID": workspace_id}, json={"decision": "accept_incoming"})
    assert first.status_code == 200, first.text
    second = owner.post(f"/api/data-sources/conflicts/{conflicts['order-two']['id']}/resolve",
        headers={"X-Workspace-ID": workspace_id}, json={"decision": "retain_existing"})
    assert second.status_code == 200, second.text
    with owner.app.state.test_session_factory() as db:
        from sqlalchemy import select
        from app.models import BusinessEvent
        current = db.scalars(select(BusinessEvent).where(BusinessEvent.workspace_id == workspace_id,
            BusinessEvent.event_type == "order", BusinessEvent.entity_id == "order-shared",
            BusinessEvent.is_current.is_(True), BusinessEvent.reconciliation_status == "accepted")).all()
        assert len(current) == 1 and float(current[0].amount) == 110
        assert second.json()["selected_event_id"] == current[0].id


def test_stale_matched_conflict_requires_refresh_after_original_is_deleted(clients):
    owner, _ = clients
    workspace_id = register(owner)
    original = create_source(owner, workspace_id, "stale-original")
    incoming = create_source(owner, workspace_id, "stale-incoming")
    base = {"source_event_id": "order-original", "event_type": "order", "occurred_at": "2026-06-01T10:00:00Z",
            "entity_id": "order-stale", "amount": "100", "currency": "USD"}
    owner.post(f"/api/integrations/google-sheets/{original['id']}/ingest", json=batch([base]),
        headers={"Authorization": f"Bearer {original['ingestion_token']}"})
    changed = {**base, "source_event_id": "order-new", "amount": "120"}
    owner.post(f"/api/integrations/google-sheets/{incoming['id']}/ingest", json=batch([changed], "incoming-0002"),
        headers={"Authorization": f"Bearer {incoming['ingestion_token']}"})
    quality = owner.get("/api/data-sources/quality", headers={"X-Workspace-ID": workspace_id}).json()
    conflict = next(row for row in quality["conflicts"] if row["status"] == "conflict")
    deleted = owner.post(f"/api/integrations/google-sheets/{original['id']}/ingest",
        json={"request_id": "delete-original-1", "deleted_source_event_ids": ["order-original"]},
        headers={"Authorization": f"Bearer {original['ingestion_token']}"})
    assert deleted.status_code == 200
    resolution = owner.post(f"/api/data-sources/conflicts/{conflict['id']}/resolve",
        headers={"X-Workspace-ID": workspace_id}, json={"decision": "accept_incoming"})
    assert resolution.status_code == 409
    assert "stale" in resolution.json()["detail"]


def test_marking_conflict_duplicate_deactivates_incoming_record(clients):
    client, _ = clients
    workspace_id = register(client)
    source_a = create_source(client, workspace_id, "duplicate-review-a")
    source_b = create_source(client, workspace_id, "duplicate-review-b")
    original = {"source_event_id": "order-a", "event_type": "order", "occurred_at": "2026-06-01T10:00:00Z",
                "entity_id": "order-dup-review", "amount": "100", "currency": "USD"}
    incoming = {**original, "source_event_id": "order-b", "amount": "105"}
    for source, record, request_id in ((source_a, original, "duplicate-base-1"),
                                       (source_b, incoming, "duplicate-incoming-1")):
        response = client.post(f"/api/integrations/google-sheets/{source['id']}/ingest",
            json=batch([record], request_id), headers={"Authorization": f"Bearer {source['ingestion_token']}"})
        assert response.status_code == 200
    quality = client.get("/api/data-sources/quality", headers={"X-Workspace-ID": workspace_id}).json()
    conflict = next(row for row in quality["conflicts"] if row["status"] == "conflict")
    result = client.post(f"/api/data-sources/conflicts/{conflict['id']}/resolve",
        headers={"X-Workspace-ID": workspace_id}, json={"decision": "mark_duplicate", "note": "Duplicate ledger entry"})
    assert result.status_code == 200
    with client.app.state.test_session_factory() as db:
        from sqlalchemy import select
        from app.models import BusinessEvent
        records = db.scalars(select(BusinessEvent).where(BusinessEvent.workspace_id == workspace_id,
            BusinessEvent.entity_id == "order-dup-review")).all()
        assert [(row.reconciliation_status, row.is_current) for row in records].count(("accepted", True)) == 1
        assert [(row.reconciliation_status, row.is_current) for row in records].count(("duplicate", False)) == 1


def test_concurrent_ingestion_cannot_activate_duplicate_business_event(clients, tmp_path):
    client, _ = clients
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db import Base, get_db
    from app.main import app

    engine = create_engine(f"sqlite:///{tmp_path / 'parallel-ingest.db'}",
                           connect_args={"check_same_thread": False, "timeout": 30})
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    previous_override = app.dependency_overrides[get_db]
    previous_factory = app.state.test_session_factory

    def override_db():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.state.test_session_factory = factory
    try:
        _test_concurrent_ingestion(client, factory)
    finally:
        app.dependency_overrides[get_db] = previous_override
        app.state.test_session_factory = previous_factory
        engine.dispose()


def _test_concurrent_ingestion(client, factory):
    workspace_id = register(client, industry="appointments")
    sources = [create_source(client, workspace_id, "concurrent-sync-a"),
               create_source(client, workspace_id, "concurrent-sync-b")]
    event = {"event_type": "appointment_outcome",
             "occurred_at": "2026-06-01T10:00:00Z", "entity_id": "appointment-unique", "status": "booked"}

    def send(index, request_id):
        source = sources[index]
        row = {**event, "source_event_id": f"appointment-row-{index}", "status": "booked" if index == 0 else "completed"}
        return client.post(f"/api/integrations/google-sheets/{source['id']}/ingest",
                           json=batch([row], request_id),
                           headers={"Authorization": f"Bearer {source['ingestion_token']}"}).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(lambda args: send(*args),
                                 ((0, "parallel-request-1"), (1, "parallel-request-2"))))
    assert all(status in (200, 409) for status in statuses)
    with factory() as db:
        from sqlalchemy import select
        from app.models import BusinessEvent
        current = db.scalars(select(BusinessEvent).where(BusinessEvent.workspace_id == workspace_id,
            BusinessEvent.event_type == "appointment_outcome", BusinessEvent.entity_id == "appointment-unique",
            BusinessEvent.is_current.is_(True), BusinessEvent.reconciliation_status == "accepted")).all()
        assert len(current) == 1
