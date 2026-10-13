"""Financial API contracts using real imports, period selection, and tenant membership."""
from datetime import date, timedelta

import pytest

from app.industries import PACKS
from tests.conftest import register
from tests.test_foundation import ECOMMERCE, upload


def detailed_csv(*rows, industry="ecommerce"):
    rows = [row if len(row.split(",")) == len(PACKS[industry].detailed_csv_columns)
            else f"{row},0" for row in rows]
    return ",".join(PACKS[industry].detailed_csv_columns) + "\n" + "\n".join(rows) + "\n"


STORE_ROW = "2026-01-01,1000,100,10,7,2,3,100,300,50,20,30"


def overview(client, **period):
    response = client.get("/api/dashboard", params=period)
    assert response.status_code == 200, response.text
    return response.json()


def test_net_profit_refund_percentage_and_weighted_fulfillment(clients):
    client, _ = clients
    register(client)
    assert upload(client, detailed_csv(STORE_ROW, "2026-01-02,900,0,90,81,0,4,0,0,0,0,0")).status_code == 200
    result = overview(client)
    for metric, expected in {"gross_revenue": 1900, "refunds": 100, "net_revenue": 1800,
                             "variable_costs": 400, "estimated_profit": 1300, "unattributed_revenue_ad_spend_ratio": 18,
                             "average_order_value": 18, "fulfillment_rate": 88,
                             "cancellation_rate": 2, "refund_revenue_percentage": 5.26}.items():
        assert result["kpis"][metric] == expected
    assert "return_rate" not in result["kpis"]
    assert "refund_revenue_percentage" in result["industry"]["kpis"]
    assert result["series"][0]["revenue"] == 900
    assert result["series"][0]["variable_costs"] == 400
    assert result["data_quality"] == {"legacy_rows": 0, "detailed_rows": 2, "fixed_cost_unknown_rows": 0}


def test_fixed_costs_add_operating_profit_without_changing_contribution_profit(clients):
    client, _ = clients
    register(client)
    rows = detailed_csv("2026-01-01,1000,100,10,7,2,3,100,300,50,20,30,100",
                        "2026-01-02,900,0,90,81,0,4,0,0,0,0,0,200")
    assert upload(client, rows).status_code == 200
    result = overview(client)
    assert result["kpis"]["estimated_profit"] == 1300
    assert result["kpis"]["fixed_costs"] == 300
    assert result["kpis"]["estimated_operating_profit"] == 1000
    assert result["series"][0]["fixed_costs"] == 100
    assert "estimated_operating_profit" in result["industry"]["kpis"]


def test_previous_detailed_csv_format_remains_accepted_but_discloses_fixed_cost_gap(clients):
    client, _ = clients
    register(client)
    columns = tuple(column for column in PACKS["ecommerce"].detailed_csv_columns if column != "fixed_costs")
    content = ",".join(columns) + "\n2026-01-01,1000,0,10,8,1,2,100,300,50,20,30\n"
    assert upload(client, content).status_code == 200
    result = overview(client)
    assert result["kpis"]["estimated_profit"] == 500
    assert result["kpis"]["estimated_operating_profit"] is None
    assert result["data_quality"]["fixed_cost_unknown_rows"] == 1
    assert any(item["code"] == "legacy_metric_coverage" for item in result["findings"])


def test_decimal_money_and_refunds_from_previous_sales(clients):
    client, _ = clients
    register(client)
    content = detailed_csv("2026-01-01,0.10,0.20,1,0,0,0,0.01,0.02,0.03,0.04,0.05",
                           "2026-01-02,0.20,0,1,1,0,0,0,0,0,0,0")
    assert upload(client, content).status_code == 200
    result = overview(client)
    assert result["kpis"]["net_revenue"] == 0.1
    assert result["kpis"]["variable_costs"] == 0.14
    assert result["kpis"]["estimated_profit"] == -0.05
    assert result["kpis"]["refund_revenue_percentage"] == 66.67
    assert result["series"][0]["revenue"] == -0.1
    assert result["findings"][0]["code"] == "negative_profit"


@pytest.mark.parametrize("counts", ["10,9,2,0", "10,1,2,9", "10,11,0,0", "10,0,11,0",
                                   "10,0,0,11", "0,1,0,0", "10,7.5,0,0", "10,7,-1,0"])
def test_contradictory_order_outcomes_rejected_atomically(clients, counts):
    client, _ = clients
    register(client)
    assert upload(client, detailed_csv(STORE_ROW)).status_code == 200
    invalid = f"2026-01-02,100,0,{counts},10,20,0,0,0"
    response = upload(client, detailed_csv(STORE_ROW.replace(",1000,", ",2000,"), invalid))
    assert response.status_code == 422
    assert overview(client)["kpis"]["gross_revenue"] == 1000
    assert overview(client)["row_count"] == 1


def test_delayed_fulfilled_orders_may_overlap_and_zero_denominators_are_null(clients):
    client, _ = clients
    register(client)
    assert upload(client, detailed_csv("2026-01-01,100,0,10,10,0,10,0,0,0,0,0")).status_code == 200
    assert overview(client)["kpis"]["fulfillment_rate"] == 100
    assert upload(client, detailed_csv("2026-01-01,0,0,0,0,0,0,0,0,0,0,0")).status_code == 200
    result = overview(client)
    for metric in ("fulfillment_rate", "cancellation_rate", "average_order_value", "unattributed_revenue_ad_spend_ratio",
                   "refund_revenue_percentage"):
        assert result["kpis"][metric] is None


def test_legacy_mixed_and_replacement_imports_do_not_invent_outcomes(clients):
    client, _ = clients
    register(client)
    assert upload(client, ECOMMERCE).status_code == 200
    legacy = overview(client)
    assert legacy["kpis"]["estimated_profit"] == -20
    assert legacy["kpis"]["fulfillment_rate"] is None
    assert legacy["kpis"]["cancellation_rate"] is None
    assert legacy["data_quality"]["legacy_rows"] == 1
    assert any(item["code"] == "legacy_metric_coverage" for item in legacy["findings"])
    assert upload(client, detailed_csv(STORE_ROW.replace("01-01", "01-02"))).status_code == 200
    assert overview(client)["kpis"]["fulfillment_rate"] is None
    detail = overview(client, start_date="2026-01-02", end_date="2026-01-02")
    assert detail["kpis"]["fulfillment_rate"] == 70
    assert detail["kpis"]["refund_revenue_percentage"] == 10
    # Replacement clears normalized outcomes and refunds rather than retaining the old values.
    assert upload(client, ECOMMERCE.replace("01-01", "01-02")).status_code == 200
    replaced = overview(client)
    assert replaced["kpis"]["refunds"] == 0
    assert replaced["kpis"]["fulfillment_rate"] is None
    assert replaced["kpis"]["estimated_profit"] == -40
    assert replaced["data_quality"] == {"legacy_rows": 2, "detailed_rows": 0, "fixed_cost_unknown_rows": 2}


def test_reporting_period_gaps_empty_ranges_and_tenant_isolation(clients):
    first, second = clients
    tenant_a = register(first)
    register(second, "second@example.com")
    assert upload(first, detailed_csv(STORE_ROW, STORE_ROW.replace("01-01", "01-03"))).status_code == 200
    assert upload(second, detailed_csv(STORE_ROW.replace(",1000,", ",9000,"))).status_code == 200
    full = overview(first)
    assert full["reporting_period"] == {"start": "2026-01-01", "end": "2026-01-03", "observed_days": 2,
                                         "calendar_days": 3, "missing_days": 1, "complete": False}
    assert full["kpis"]["gross_revenue"] == 2000
    window = overview(first, start_date="2025-12-31", end_date="2026-01-02")
    assert window["row_count"] == 1
    assert window["reporting_period"]["missing_days"] == 2
    assert window["kpis"]["estimated_profit"] == 400
    assert [row["date"] for row in window["series"]] == ["2026-01-01"]
    empty = overview(first, start_date="2026-02-01", end_date="2026-02-03")
    assert empty["row_count"] == 0 and empty["series"] == []
    assert empty["reporting_period"]["missing_days"] == 3
    assert empty["reporting_period"]["complete"] is False
    assert empty["kpis"]["fulfillment_rate"] is None
    assert second.get("/api/dashboard", params={"start_date": "2026-01-01", "end_date": "2026-01-03"},
                      headers={"X-Workspace-ID": tenant_a}).status_code == 403


@pytest.mark.parametrize("period", [{"start_date": "2026-01-01"}, {"end_date": "2026-01-01"},
                                    {"start_date": "2026-01-02", "end_date": "2026-01-01"},
                                    {"start_date": "bad", "end_date": "2026-01-01"},
                                    {"start_date": "2026-01-01", "end_date": "2027-01-02"}])
def test_invalid_reporting_periods(clients, period):
    client, _ = clients
    register(client)
    assert client.get("/api/dashboard", params=period).status_code == 422


@pytest.mark.parametrize("end_date", ["2026-01-18", "2026-01-19"])
def test_weekly_net_revenue_compares_complete_calendar_weeks_including_sunday(clients, end_date):
    client, _ = clients
    register(client)
    rows = [f"{date(2026, 1, 5) + timedelta(days=i)},200,{0 if i < 7 else 100},10,8,1,2,10,20,0,0,0"
            for i in range(14)]
    assert upload(client, detailed_csv(*rows)).status_code == 200
    result = overview(client, start_date="2026-01-05", end_date=end_date)
    finding = next(item for item in result["findings"] if item["code"] == "revenue_drop")
    assert "1400.00" in finding["evidence"] and "700.00" in finding["evidence"]


def test_weekly_drop_requires_all_fourteen_dates(clients):
    client, _ = clients
    register(client)
    rows = [f"{date(2026, 1, 5) + timedelta(days=i)},200,{0 if i < 7 else 100},10,8,1,2,10,20,0,0,0"
            for i in range(14) if i != 5]
    assert upload(client, detailed_csv(*rows)).status_code == 200
    result = overview(client)
    assert result["reporting_period"]["missing_days"] == 1
    assert not any(item["code"] == "revenue_drop" for item in result["findings"])


def test_appointment_costs_refunds_and_exclusive_outcomes(clients):
    client, _ = clients
    register(client, industry="appointments")
    row = "2026-01-01,100,10,10,6,3,20,30,5"
    assert upload(client, detailed_csv(row, industry="appointments")).status_code == 200
    result = overview(client)
    assert result["kpis"]["net_revenue"] == 90
    assert result["kpis"]["estimated_profit"] == 35
    assert result["kpis"]["completion_rate"] == 60
    assert result["kpis"]["cancellation_rate"] == 30
    assert upload(client, detailed_csv(row.replace(",6,3,", ",8,3,"), industry="appointments")).status_code == 422


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-0.01", "0.001", "1000000001", "invalid"])
def test_invalid_money_is_rejected(clients, value):
    client, _ = clients
    register(client)
    assert upload(client, detailed_csv(STORE_ROW.replace(",1000,", f",{value},"))).status_code == 422
    assert overview(client)["row_count"] == 0
