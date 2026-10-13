import io
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from types import SimpleNamespace

import pandas as pd
from fastapi import HTTPException
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.industries import IndustryPack
from app.models import BusinessEvent, DailyMetric, DataCoverage, Workspace

MAX_UPLOAD_BYTES = 2 * 1024 * 1024
CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def reconciled_metric_rows(db: Session, workspace: Workspace, pack: IndustryPack,
                           start_date: date | None, end_date: date | None) -> tuple[list, dict | None]:
    query = select(BusinessEvent).where(BusinessEvent.workspace_id == workspace.id,
                                        BusinessEvent.reconciliation_status == "accepted",
                                        BusinessEvent.is_current.is_(True))
    if pack.code == "appointments" and (start_date or end_date):
        date_columns = (BusinessEvent.occurred_at, BusinessEvent.booked_at,
                        BusinessEvent.scheduled_at, BusinessEvent.completed_at)
        date_clauses = []
        for column in date_columns:
            bounds = []
            if start_date:
                bounds.append(column >= start_date)
            if end_date:
                bounds.append(column < end_date + timedelta(days=1))
            date_clauses.append(and_(*bounds))
        query = query.where(or_(*date_clauses))
    else:
        if start_date:
            query = query.where(BusinessEvent.occurred_at >= start_date)
        if end_date:
            query = query.where(BusinessEvent.occurred_at < end_date + timedelta(days=1))
    events = db.scalars(query.order_by(BusinessEvent.occurred_at, BusinessEvent.id)).all()
    coverage_query = select(DataCoverage).where(DataCoverage.workspace_id == workspace.id,
                                                DataCoverage.is_current.is_(True))
    if start_date:
        coverage_query = coverage_query.where(DataCoverage.day >= start_date)
    if end_date:
        coverage_query = coverage_query.where(DataCoverage.day <= end_date)
    coverage = db.scalars(coverage_query).all()
    unresolved_query = select(BusinessEvent).where(
        BusinessEvent.workspace_id == workspace.id,
        BusinessEvent.reconciliation_status.in_(("conflict", "missing")),
    )
    if start_date:
        unresolved_query = unresolved_query.where(BusinessEvent.occurred_at >= start_date)
    if end_date:
        unresolved_query = unresolved_query.where(BusinessEvent.occurred_at < end_date + timedelta(days=1))
    unresolved = db.scalars(unresolved_query).all()
    if not events and not coverage and not unresolved:
        return [], None
    groups: dict[date, dict] = {}
    campaigns: dict[str, Decimal] = {}
    unmatched_payments = Decimal("0")
    event_types = set()
    def empty_group():
        return {"gross_revenue": Decimal("0"), "refunds": Decimal("0"), "ad_spend": Decimal("0"),
            "variable_costs": Decimal("0"), "fixed_costs": Decimal("0"), "orders": 0,
            "fulfilled_orders": 0, "cancelled_orders": 0, "delayed_orders": 0, "bookings": 0,
            "scheduled_appointments": 0, "completed_appointments": 0,
            "completed_for_bookings": 0, "cancelled_appointments": 0,
            "has_fulfillment": False, "has_cancellation": False, "has_fixed_cost": False,
            "has_variable_cost": False}

    def group_for(day):
        return groups.setdefault(day, empty_group())

    cancelled_entities = {event.entity_id for event in events if event.event_type == "cancellation" and event.entity_id}
    for event in events:
        day = event.occurred_at.date()
        group = None if pack.code == "appointments" and event.event_type == "appointment_outcome" else group_for(day)
        event_types.add(event.event_type)
        amount = Decimal(str(event.amount or 0))
        if event.event_type == "payment" and event.status_value == "captured":
            group["gross_revenue"] += amount
            if event.campaign_id:
                campaigns[event.campaign_id] = campaigns.get(event.campaign_id, Decimal("0")) + amount
            else:
                unmatched_payments += amount
        elif event.event_type == "refund":
            group["refunds"] += amount
        elif event.event_type == "marketing_spend":
            group["ad_spend"] += amount
        elif event.event_type == "expense":
            field = "fixed_costs" if event.cost_category == "fixed" else "variable_costs"
            group[field] += amount
            group["has_fixed_cost" if field == "fixed_costs" else "has_variable_cost"] = True
        elif pack.code == "ecommerce" and event.event_type == "order":
            group["orders"] += event.quantity
        elif pack.code == "ecommerce" and event.event_type == "fulfillment":
            group["has_fulfillment"] = True
            if event.status_value == "fulfilled" and event.entity_id not in cancelled_entities:
                group["fulfilled_orders"] += event.quantity
            elif event.status_value == "delayed" and event.entity_id not in cancelled_entities:
                group["delayed_orders"] += event.quantity
        elif pack.code == "ecommerce" and event.event_type == "cancellation":
            group["has_cancellation"] = True
            group["cancelled_orders"] += event.quantity
        elif pack.code == "appointments" and event.event_type == "appointment_outcome":
            booking_day = (event.booked_at or event.occurred_at).date()
            group_for(booking_day)["bookings"] += event.quantity
            if event.scheduled_at:
                group_for(event.scheduled_at.date())["scheduled_appointments"] += event.quantity
            if event.status_value == "completed":
                completion_day = (event.completed_at or event.occurred_at).date()
                group_for(completion_day)["completed_appointments"] += event.quantity
                group_for(booking_day)["completed_for_bookings"] += event.quantity
            elif event.status_value == "cancelled":
                group_for(day)["cancelled_appointments"] += event.quantity
    complete_days = {}
    declared_coverage = {}
    for item in coverage:
        declared_coverage.setdefault((item.day, item.data_kind), []).append((item.source_id, item.complete))
        if item.complete:
            complete_days.setdefault(item.day, set()).add(item.data_kind)
        group_for(item.day)
    for (coverage_day, kind), declarations in declared_coverage.items():
        if any(not complete for _, complete in declarations):
            complete_days.get(coverage_day, set()).discard(kind)
    event_kind = {"payment": "payments", "refund": "refunds", "marketing_spend": "marketing_spend",
                  "order": "orders", "fulfillment": "fulfillment", "cancellation": "orders",
                  "appointment_outcome": "appointments"}
    for event in events:
        if event.event_type == "expense":
            kind = "fixed_costs" if event.cost_category == "fixed" else "variable_costs"
        else:
            kind = event_kind.get(event.event_type)
        if kind:
            event_day = event.occurred_at.date()
            declared_sources = {source_id for source_id, complete in declared_coverage.get((event_day, kind), [])
                                if complete}
            if event.source_id not in declared_sources:
                complete_days.get(event_day, set()).discard(kind)
    for event in unresolved:
        group_for(event.occurred_at.date())
        if event.event_type == "expense" and event.cost_category is None:
            kinds = ("fixed_costs", "variable_costs")
        elif event.event_type == "expense":
            kinds = ("fixed_costs" if event.cost_category == "fixed" else "variable_costs",)
        else:
            kinds = (event_kind.get(event.event_type),)
        for kind in kinds:
            if kind:
                complete_days.get(event.occurred_at.date(), set()).discard(kind)
    if start_date:
        groups = {day: group for day, group in groups.items() if day >= start_date}
    if end_date:
        groups = {day: group for day, group in groups.items() if day <= end_date}
    rows = []
    for day, group in groups.items():
        version = 3 if {"fixed_costs", "variable_costs"} <= complete_days.get(day, set()) else 2
        rows.append(SimpleNamespace(
            day=day, values={"orders": group["orders"], "bookings": group["bookings"],
                             "scheduled": group["scheduled_appointments"],
                             "completed": group["completed_appointments"],
                             "completed_for_bookings": group["completed_for_bookings"],
                             "cancelled": group["cancelled_appointments"]},
            schema_version=version, gross_revenue=group["gross_revenue"], refunds=group["refunds"],
            ad_spend=group["ad_spend"], variable_costs=group["variable_costs"], fixed_costs=group["fixed_costs"],
            orders=group["orders"], fulfilled_orders=group["fulfilled_orders"] if group["has_fulfillment"] else None,
            cancelled_orders=group["cancelled_orders"] if group["has_cancellation"] else None,
            delayed_orders=group["delayed_orders"] if group["has_fulfillment"] else None,
            bookings=group["bookings"], completed_appointments=group["completed_appointments"],
            scheduled_appointments=group["scheduled_appointments"],
            completed_for_bookings=group["completed_for_bookings"],
            cancelled_appointments=group["cancelled_appointments"] if group["bookings"] else None,
        ))
    required_types = ({"order", "payment", "refund", "fulfillment", "cancellation", "marketing_spend", "expense"}
                      if pack.code == "ecommerce" else
                      {"appointment_outcome", "payment", "refund", "marketing_spend", "expense"})
    for row in rows:
        kinds = complete_days.get(row.day, set())
        row.financial_complete = {"payments": "payments" in kinds, "refunds": "refunds" in kinds,
                                  "marketing_spend": "marketing_spend" in kinds,
                                  "variable_costs": "variable_costs" in kinds,
                                  "fixed_costs": "fixed_costs" in kinds}
    return rows, {"accepted_events": len(events), "observed_event_types": sorted(event_types),
                  "complete_cost_days": sorted(day.isoformat() for day, kinds in complete_days.items()
                                               if {"variable_costs", "fixed_costs"} <= kinds),
                  "missing_event_types": sorted(required_types - event_types),
                  "recorded_campaign_payments": {key: float(value) for key, value in sorted(campaigns.items())},
                  "payments_without_campaign_id": float(unmatched_payments),
                  "campaign_interpretation": "Recorded campaign identifiers are source labels only; they do not establish advertising causality or attribution."}


def parse_csv(content: bytes, pack: IndustryPack) -> list[tuple[date, dict, int]]:
    try:
        frame = pd.read_csv(io.BytesIO(content), dtype=str, keep_default_na=False)
        columns = tuple(frame.columns)
        version_two_columns = tuple(column for column in pack.detailed_csv_columns if column != "fixed_costs")
        if set(columns) == set(pack.detailed_csv_columns):
            schema_version, expected = 3, pack.detailed_csv_columns
        elif set(columns) == set(version_two_columns):
            schema_version, expected = 2, version_two_columns
        else:
            schema_version, expected = 1, pack.csv_columns
        if len(columns) != len(set(columns)) or set(columns) != set(expected):
            raise ValueError(f"Use either complete CSV header: {', '.join(pack.csv_columns)}; or: "
                             f"{', '.join(pack.detailed_csv_columns)}")
        if not 1 <= len(frame) <= 10_000:
            raise ValueError("Import between 1 and 10,000 daily rows")
        days = [date.fromisoformat(value) for value in frame["date"]]
        if len(set(days)) != len(days):
            raise ValueError("Each date must appear once per file")
        records: list[tuple[date, dict, int]] = []
        for day, row in zip(days, frame.to_dict("records"), strict=True):
            amount_keys = {key for key in expected if key not in {
                "date", "orders", "fulfilled_orders", "cancelled_orders", "delayed_orders",
                "bookings", "completed", "cancelled",
            }}
            values = {}
            for key in amount_keys:
                try:
                    amount = Decimal(row[key])
                except InvalidOperation:
                    raise ValueError(f"{key} must be a valid amount") from None
                if (not amount.is_finite() or amount < 0 or amount > Decimal("1000000000")
                        or amount != amount.quantize(CENT, rounding=ROUND_HALF_UP)):
                    raise ValueError(f"{key} must be a nonnegative amount with at most two decimal places")
                values[key] = str(amount.quantize(CENT))
            count_keys = {key for key in expected if key in {
                "orders", "fulfilled_orders", "cancelled_orders", "delayed_orders",
                "bookings", "completed", "cancelled",
            }}
            for key in count_keys:
                try:
                    count = Decimal(row[key])
                except InvalidOperation:
                    raise ValueError(f"{key} must be a whole number") from None
                if not count.is_finite() or count < 0 or count > 1_000_000_000 or count != count.to_integral_value():
                    raise ValueError(f"{key} must be a nonnegative whole number")
                values[key] = int(count)
            revenue_key = "gross_revenue" if schema_version >= 2 else "revenue"
            values["revenue"] = values[revenue_key]
            if schema_version >= 2:
                if pack.code == "ecommerce":
                    for outcome in ("fulfilled_orders", "cancelled_orders", "delayed_orders"):
                        if values[outcome] > values["orders"]:
                            raise ValueError(f"{outcome} cannot exceed orders")
                    # Fulfilled and cancelled are exclusive final outcomes. Delayed is a
                    # timing flag: it may include fulfilled orders, but never cancelled ones.
                    if values["fulfilled_orders"] + values["cancelled_orders"] > values["orders"]:
                        raise ValueError("Fulfilled and cancelled orders cannot exceed orders")
                    if values["delayed_orders"] + values["cancelled_orders"] > values["orders"]:
                        raise ValueError("Delayed and cancelled orders cannot exceed orders")
                elif values["completed"] + values["cancelled"] > values["bookings"]:
                    raise ValueError("Completed and cancelled appointments cannot exceed bookings")
            if "completed" in values and values["completed"] > values["bookings"]:
                raise ValueError("Completed appointments cannot exceed bookings")
            records.append((day, values, schema_version))
        return records
    except (ValueError, UnicodeError, pd.errors.ParserError, pd.errors.EmptyDataError) as error:
        raise HTTPException(422, str(error)) from None


def dashboard(db: Session, workspace: Workspace, pack: IndustryPack,
              start_date: date | None = None, end_date: date | None = None) -> dict:
    if start_date and end_date and start_date > end_date:
        raise ValueError("Reporting period start must be on or before its end")
    query = select(DailyMetric).where(DailyMetric.workspace_id == workspace.id)
    if start_date:
        query = query.where(DailyMetric.day >= start_date)
    if end_date:
        query = query.where(DailyMetric.day <= end_date)
    rows = db.scalars(query.order_by(DailyMetric.day)).all()
    event_rows, source_metrics = reconciled_metric_rows(db, workspace, pack, start_date, end_date)
    csv_dates = {row.day for row in rows}
    overlap_dates = sorted(csv_dates & {row.day for row in event_rows})
    # A CSV aggregate is retained on date overlap until the sources can be compared safely.
    # Event batches can be partial, so accepting them over an aggregate would lose fields.
    if event_rows:
        by_date = {row.day: row for row in rows}
        by_date.update({row.day: row for row in event_rows if row.day not in csv_dates})
        rows = [by_date[day] for day in sorted(by_date)]
        source_metrics["csv_overlap_dates"] = [day.isoformat() for day in overlap_dates]
    def money(value):
        return Decimal(str(value or 0))
    gross = sum((money(row.gross_revenue) for row in rows), ZERO)
    refunds = sum((money(row.refunds) for row in rows), ZERO)
    revenue = gross - refunds
    spend = sum((money(row.ad_spend) for row in rows), ZERO)
    cost = sum((money(row.variable_costs) for row in rows), ZERO)
    fixed_cost = sum((money(row.fixed_costs) for row in rows), ZERO)
    event_days = {row.day for row in event_rows}
    fixed_costs_complete = (all(row.schema_version >= 3 for row in rows if row.day not in event_days)
                            and all(row.financial_complete["fixed_costs"] for row in event_rows))
    financial_complete = not event_days or all(
        all(row.financial_complete[kind] for kind in ("payments", "refunds", "marketing_spend", "variable_costs"))
        for row in event_rows if row.day in event_days
    )
    operating_profit_complete = financial_complete and fixed_costs_complete
    profit = revenue - spend - cost
    def count(name, attr=None):
        return sum(int((row.values.get(name) if attr is None else getattr(row, attr)) or 0) for row in rows)
    totals = {"revenue": float(revenue), "gross_revenue": float(gross), "refunds": float(refunds),
              "ad_spend": float(spend), "variable_costs": float(cost), "fixed_costs": float(fixed_cost)}
    if pack.code == "ecommerce":
        totals.update(orders=count("orders", "orders"), fulfilled_orders=count("fulfilled_orders", "fulfilled_orders"),
                      cancelled_orders=count("cancelled_orders", "cancelled_orders"),
                      delayed_orders=count("delayed_orders", "delayed_orders"))
    else:
        totals.update(bookings=count("bookings", "bookings"), completed=count("completed", "completed_appointments"),
                      scheduled_appointments=count("scheduled"),
                      cancelled=count("cancelled", "cancelled_appointments"))
    kpis = {**totals, "net_revenue": (float(revenue) if financial_complete else None),
            "estimated_profit": (float(profit.quantize(CENT)) if financial_complete else None),
            "estimated_operating_profit": (float((profit - fixed_cost).quantize(CENT))
                                            if operating_profit_complete else None),
            "refund_revenue_percentage": (float((refunds / gross * 100).quantize(CENT))
                                          if financial_complete and gross else None),
            "unattributed_revenue_ad_spend_ratio": (float((revenue / spend).quantize(CENT))
                                                       if financial_complete and spend else None)}
    volume = totals[pack.volume_column]
    if pack.code == "ecommerce":
        kpis["average_order_value"] = float((revenue / volume).quantize(CENT)) if volume else None
        fulfillment_known = bool(rows) and all(row.fulfilled_orders is not None for row in rows)
        cancellations_known = bool(rows) and all(row.cancelled_orders is not None for row in rows)
        kpis["fulfillment_rate"] = (
            round(totals["fulfilled_orders"] / totals["orders"] * 100, 2)
            if fulfillment_known and totals["orders"] else None
        )
        kpis["cancellation_rate"] = (
            round(totals["cancelled_orders"] / totals["orders"] * 100, 2)
            if cancellations_known and totals["orders"] else None
        )
    else:
        completed_booking_cohort = sum(int(row.values.get("completed_for_bookings", row.values.get("completed", 0)) or 0)
                                       for row in rows)
        kpis["completion_rate"] = (round(completed_booking_cohort / totals["bookings"] * 100, 2)
                                   if totals["bookings"] else None)
        cancellations_known = bool(rows) and all(row.cancelled_appointments is not None for row in rows)
        kpis["cancellation_rate"] = (
            round(totals["cancelled"] / totals["bookings"] * 100, 2)
            if cancellations_known and totals["bookings"] else None
        )
    findings = []
    if financial_complete and rows and profit < 0:
        findings.append({"code": "negative_profit", "title": "Variable costs exceed net revenue",
                         "evidence": f"Net revenue {revenue:.2f}, refunds {refunds:.2f}, ad spend {spend:.2f}, "
                                     f"variable costs {cost:.2f}.",
                         "severity": "high"})
    if operating_profit_complete and profit - fixed_cost < 0:
        findings.append({"code": "negative_operating_profit", "title": "Reported fixed costs exceed contribution profit",
                         "evidence": f"Contribution profit {profit:.2f}, reported fixed costs {fixed_cost:.2f}, "
                                     f"estimated operating profit {(profit - fixed_cost):.2f}.",
                         "severity": "high"})
    if financial_complete and pack.code == "ecommerce" and spend > 0 and revenue / spend < 1:
        findings.append({"code": "low_unattributed_revenue_ad_spend_ratio", "title": "Ad spend exceeds net revenue",
                         "evidence": f"Net revenue / ad spend is {revenue / spend:.2f}; this is not attribution.", "severity": "high"})
    if pack.code == "appointments" and totals["bookings"] and kpis["completion_rate"] < 80:
        findings.append({"code": "low_completion_rate", "title": "Appointment completion below 80%",
                         "evidence": f"{completed_booking_cohort:.0f} completed out of {totals['bookings']:.0f} bookings.",
                         "severity": "medium"})
    period_start, period_end = start_date or (rows[0].day if rows else None), end_date or (rows[-1].day if rows else None)
    period_days = (period_end - period_start).days + 1 if period_start and period_end else 0
    coverage = {"start": period_start, "end": period_end, "observed_days": len(rows),
                "calendar_days": period_days, "missing_days": max(period_days - len(rows), 0),
                "complete": bool(period_days and len(rows) == period_days)}
    if source_metrics:
        source_metrics["financial_completeness"] = {"contribution_complete": financial_complete,
            "complete": operating_profit_complete,
            "per_day": {row.day.isoformat(): row.financial_complete for row in event_rows},
            "note": "A zero amount is complete only when its source explicitly marks that day and data kind complete."}
    versions = {row.schema_version for row in rows}
    if versions - {3}:
        findings.append({"code": "legacy_metric_coverage", "title": "Some imports omit detailed cost fields",
                         "evidence": "Rows without the latest detailed schema treat unreported refunds, additional costs, or fixed costs as zero in estimates.",
                         "severity": "low"})
    # Only compare completed, fully observed calendar weeks; missing dates are not zero sales.
    by_day = {row.day: row for row in rows}
    if period_end and period_days >= 14:
        current_week_end = period_end - timedelta(days=(period_end.weekday() - 6) % 7)
        current_start = current_week_end - timedelta(days=6)
        previous_start = current_start - timedelta(days=7)
        previous_days = [previous_start + timedelta(days=i) for i in range(7)]
        current_days = [current_start + timedelta(days=i) for i in range(7)]
        if all(day in by_day for day in previous_days + current_days):
            previous = sum((money(by_day[day].gross_revenue) - money(by_day[day].refunds) for day in previous_days), ZERO)
            recent = sum((money(by_day[day].gross_revenue) - money(by_day[day].refunds) for day in current_days), ZERO)
            if previous and recent < previous * Decimal("0.8"):
                findings.append({"code": "revenue_drop", "title": "Weekly net revenue fell more than 20%",
                                 "evidence": f"Previous complete week: {previous:.2f}; latest complete week: {recent:.2f}.",
                                 "severity": "medium"})
    series = [{"date": row.day, **row.values, "revenue": float(money(row.gross_revenue) - money(row.refunds)),
               "gross_revenue": float(money(row.gross_revenue)), "refunds": float(money(row.refunds)),
               "ad_spend": float(money(row.ad_spend)), "variable_costs": float(money(row.variable_costs)),
               "fixed_costs": float(money(row.fixed_costs))}
              for row in rows]
    response = {"business_name": workspace.name, "industry": pack.public(), "currency": workspace.currency,
            "row_count": len(rows), "period_start": rows[0].day if rows else None,
            "period_end": rows[-1].day if rows else None, "reporting_period": coverage,
            "kpis": kpis, "findings": findings, "series": series,
            "data_quality": {"legacy_rows": sum(row.schema_version == 1 for row in rows),
                             "detailed_rows": sum(row.schema_version >= 2 for row in rows),
                             "fixed_cost_unknown_rows": sum(row.schema_version < 3 for row in rows)},
            "profit_note": "Estimated contribution profit = gross revenue − refunds − ad spend − reported variable costs. "
                           "Estimated operating profit also subtracts reported fixed costs. Fixed costs should be allocated to each date only once. "
                           "Both estimates exclude taxes and unreported costs and are not accounting profit. The unattributed revenue/ad-spend ratio uses net revenue "
                           "without campaign attribution, so it is not an attributable advertising return metric. "
                           "Legacy imports have no reported refunds or fulfillment outcomes."}
    if source_metrics is not None:
        response["source_metrics"] = source_metrics
        response["data_quality"]["reconciled_event_rows"] = len(event_rows)
        response["data_quality"]["event_type_coverage_gaps"] = source_metrics["missing_event_types"]
        response["data_quality"]["source_overlap_days"] = len(overlap_dates)
    return response
