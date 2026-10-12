from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class IndustryPack:
    code: str
    name: str
    description: str
    csv_columns: tuple[str, ...]
    volume_column: str
    cost_column: str
    kpis: tuple[str, ...]
    diagnostics: tuple[str, ...]
    experiment_types: tuple[str, ...]

    def public(self) -> dict:
        return asdict(self)


PACKS = {
    "ecommerce": IndustryPack(
        code="ecommerce", name="E-commerce",
        description="Online stores selling products.",
        csv_columns=("date", "revenue", "orders", "ad_spend", "cost_of_goods"),
        volume_column="orders", cost_column="cost_of_goods",
        kpis=("revenue", "orders", "estimated_profit", "roas", "average_order_value"),
        diagnostics=("negative_profit", "low_roas", "revenue_drop"),
        experiment_types=("offer", "landing_page", "audience", "checkout"),
    ),
    "appointments": IndustryPack(
        code="appointments", name="Appointment-based",
        description="Salons, clinics, and businesses selling scheduled services.",
        csv_columns=("date", "revenue", "bookings", "completed", "ad_spend", "variable_cost"),
        volume_column="completed", cost_column="variable_cost",
        kpis=("revenue", "bookings", "completed", "estimated_profit", "completion_rate", "roas"),
        diagnostics=("negative_profit", "low_completion_rate", "revenue_drop"),
        experiment_types=("reminder", "rebooking", "service_bundle", "local_audience"),
    ),
}
