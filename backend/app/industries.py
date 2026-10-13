from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class GrowthPlay:
    diagnostic: str
    action_type: str
    title: str
    action: str
    hypothesis: str
    metric: str
    goal_keywords: tuple[str, ...]
    blocked_constraints: tuple[str, ...] = ()


@dataclass(frozen=True)
class IndustryPack:
    code: str
    name: str
    description: str
    csv_columns: tuple[str, ...]
    detailed_csv_columns: tuple[str, ...]
    volume_column: str
    cost_column: str
    kpis: tuple[str, ...]
    diagnostics: tuple[str, ...]
    experiment_types: tuple[str, ...]
    growth_plays: tuple[GrowthPlay, ...] = ()
    minimum_experiment_volume: int = 30

    def public(self) -> dict:
        return asdict(self)


PACKS = {
    "ecommerce": IndustryPack(
        code="ecommerce", name="E-commerce",
        description="Online stores selling products.",
        csv_columns=("date", "revenue", "orders", "ad_spend", "cost_of_goods"),
        detailed_csv_columns=("date", "gross_revenue", "refunds", "orders", "fulfilled_orders",
                              "cancelled_orders", "delayed_orders", "ad_spend", "cost_of_goods",
                              "fulfillment_cost", "payment_fees", "other_variable_costs", "fixed_costs"),
        volume_column="orders", cost_column="cost_of_goods",
        kpis=("gross_revenue", "refunds", "net_revenue", "orders", "fulfilled_orders",
              "cancelled_orders", "estimated_profit", "estimated_operating_profit", "refund_revenue_percentage", "fulfillment_rate",
              "unattributed_revenue_ad_spend_ratio", "average_order_value"),
        diagnostics=("negative_profit", "low_unattributed_revenue_ad_spend_ratio", "revenue_drop", "legacy_metric_coverage"),
        experiment_types=("offer", "landing_page", "audience", "checkout"),
        growth_plays=(
            GrowthPlay("negative_profit", "checkout", "Review unprofitable order economics",
                       "Review item margins and checkout shipping charges; test clearer cost information without discounting.",
                       "Clearer shipping and cost information may improve contribution profit; the cause is not established.",
                       "estimated_profit", ("profit", "margin", "cost"), ("no checkout changes", "no shipping changes")),
            GrowthPlay("low_unattributed_revenue_ad_spend_ratio", "audience", "Review inefficient advertising allocation",
                       "Review segment costs and reallocate existing spend to a small pilot; do not increase total spend.",
                       "A more focused audience may improve contribution profit; aggregate unattributed revenue/ad-spend ratio does not identify a failing segment.",
                       "estimated_profit", ("profit", "marketing", "acquisition"),
                       ("no audience changes", "no ad changes", "no campaign changes")),
            GrowthPlay("revenue_drop", "landing_page", "Test clearer product and delivery information",
                       "Review the declining period and test one landing-page clarification with unchanged prices.",
                       "Clearer product and delivery information may improve daily net revenue; the decline alone does not prove a cause.",
                       "net_revenue", ("sales", "revenue", "growth"), ("no website changes", "no landing page changes")),
        ),
    ),
    "appointments": IndustryPack(
        code="appointments", name="Appointment-based",
        description="Salons, clinics, and businesses selling scheduled services.",
        csv_columns=("date", "revenue", "bookings", "completed", "ad_spend", "variable_cost"),
        detailed_csv_columns=("date", "gross_revenue", "refunds", "bookings", "completed",
                              "cancelled", "ad_spend", "variable_cost", "other_variable_costs", "fixed_costs"),
        volume_column="completed", cost_column="variable_cost",
        kpis=("gross_revenue", "refunds", "net_revenue", "bookings", "scheduled_appointments", "completed", "cancelled",
              "estimated_profit", "estimated_operating_profit", "refund_revenue_percentage", "completion_rate", "unattributed_revenue_ad_spend_ratio"),
        diagnostics=("negative_profit", "low_completion_rate", "revenue_drop", "legacy_metric_coverage"),
        experiment_types=("reminder", "rebooking", "service_bundle", "local_audience"),
        minimum_experiment_volume=20,
        growth_plays=(
            GrowthPlay("low_completion_rate", "reminder", "Test clearer appointment reminders",
                       "Review consent and existing reminder timing; test one reminder change using existing tools.",
                       "Clearer reminders may improve appointment completion; incomplete bookings do not establish a no-show cause.",
                       "completion_rate", ("completion", "attendance", "booking", "retention"),
                       ("no reminders", "no messaging", "no customer contact")),
            GrowthPlay("negative_profit", "service_bundle", "Review service contribution margins",
                       "Review service variable costs and test a clearer service bundle without lowering prices.",
                       "A clearer service bundle may improve daily contribution profit; service-level margin data still needs review.",
                       "estimated_profit", ("profit", "margin", "cost"), ("no bundles", "no service changes")),
            GrowthPlay("revenue_drop", "rebooking", "Test a consent-based rebooking invitation",
                       "Review the declining period and test one rebooking invitation through an existing consented channel.",
                       "A rebooking invitation may improve daily net revenue; the revenue decline does not identify its cause.",
                       "net_revenue", ("sales", "revenue", "retention", "booking"),
                       ("no messaging", "no customer contact", "no rebooking")),
        ),
    ),
}
