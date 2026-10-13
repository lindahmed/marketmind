"""Add normalized daily money and outcome fields with tenant/date reporting."""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    for column, type_, default in (
        ("schema_version", sa.Integer(), "1"),
        ("gross_revenue", sa.Numeric(14, 2), "0"),
        ("refunds", sa.Numeric(14, 2), "0"),
        ("ad_spend", sa.Numeric(14, 2), "0"),
        ("variable_costs", sa.Numeric(14, 2), "0"),
        ("orders", sa.Integer(), None),
        ("fulfilled_orders", sa.Integer(), None),
        ("cancelled_orders", sa.Integer(), None),
        ("delayed_orders", sa.Integer(), None),
        ("bookings", sa.Integer(), None),
        ("completed_appointments", sa.Integer(), None),
        ("cancelled_appointments", sa.Integer(), None),
    ):
        op.add_column("daily_metrics", sa.Column(column, type_, nullable=default is None,
                                                  server_default=default))

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text("""
            UPDATE daily_metrics SET
                gross_revenue = COALESCE(NULLIF("values"->>'revenue', '')::numeric,
                                         NULLIF("values"->>'gross_revenue', '')::numeric, 0),
                refunds = COALESCE(NULLIF("values"->>'refunds', '')::numeric, 0),
                ad_spend = COALESCE(NULLIF("values"->>'ad_spend', '')::numeric, 0),
                variable_costs = COALESCE(NULLIF("values"->>'cost_of_goods', '')::numeric,
                                          NULLIF("values"->>'variable_cost', '')::numeric, 0)
                    + COALESCE(NULLIF("values"->>'fulfillment_cost', '')::numeric, 0)
                    + COALESCE(NULLIF("values"->>'payment_fees', '')::numeric, 0)
                    + COALESCE(NULLIF("values"->>'other_variable_costs', '')::numeric, 0),
                orders = NULLIF("values"->>'orders', '')::numeric::integer,
                fulfilled_orders = NULLIF("values"->>'fulfilled_orders', '')::numeric::integer,
                cancelled_orders = NULLIF("values"->>'cancelled_orders', '')::numeric::integer,
                delayed_orders = NULLIF("values"->>'delayed_orders', '')::numeric::integer,
                bookings = NULLIF("values"->>'bookings', '')::numeric::integer,
                completed_appointments = NULLIF("values"->>'completed', '')::numeric::integer,
                cancelled_appointments = NULLIF("values"->>'cancelled', '')::numeric::integer
        """))
    else:
        bind.execute(sa.text("""
            UPDATE daily_metrics SET
                gross_revenue = COALESCE(CAST(json_extract("values", '$.revenue') AS NUMERIC),
                                         CAST(json_extract("values", '$.gross_revenue') AS NUMERIC), 0),
                refunds = COALESCE(CAST(json_extract("values", '$.refunds') AS NUMERIC), 0),
                ad_spend = COALESCE(CAST(json_extract("values", '$.ad_spend') AS NUMERIC), 0),
                variable_costs = COALESCE(CAST(json_extract("values", '$.cost_of_goods') AS NUMERIC),
                                          CAST(json_extract("values", '$.variable_cost') AS NUMERIC), 0)
                    + COALESCE(CAST(json_extract("values", '$.fulfillment_cost') AS NUMERIC), 0)
                    + COALESCE(CAST(json_extract("values", '$.payment_fees') AS NUMERIC), 0)
                    + COALESCE(CAST(json_extract("values", '$.other_variable_costs') AS NUMERIC), 0),
                orders = CAST(json_extract("values", '$.orders') AS INTEGER),
                fulfilled_orders = CAST(json_extract("values", '$.fulfilled_orders') AS INTEGER),
                cancelled_orders = CAST(json_extract("values", '$.cancelled_orders') AS INTEGER),
                delayed_orders = CAST(json_extract("values", '$.delayed_orders') AS INTEGER),
                bookings = CAST(json_extract("values", '$.bookings') AS INTEGER),
                completed_appointments = CAST(json_extract("values", '$.completed') AS INTEGER),
                cancelled_appointments = CAST(json_extract("values", '$.cancelled') AS INTEGER)
        """))


def downgrade():
    for column in ("cancelled_appointments", "completed_appointments", "bookings", "delayed_orders",
                   "cancelled_orders", "fulfilled_orders", "orders", "variable_costs", "ad_spend",
                   "refunds", "gross_revenue", "schema_version"):
        op.drop_column("daily_metrics", column)
