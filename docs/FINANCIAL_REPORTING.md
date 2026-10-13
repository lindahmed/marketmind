# Financial reporting

Daily metrics belong to a verified workspace and use its currency. Migration 0006 adds normalized decimal money and nullable outcome counts, backfills existing JSON rows, and retains the original JSON data. Existing rows remain schema version 1; detailed imports use version 2.

## CSV contracts

Latest detailed e-commerce template (includes fixed-cost allocation):

```csv
date,gross_revenue,refunds,orders,fulfilled_orders,cancelled_orders,delayed_orders,ad_spend,cost_of_goods,fulfillment_cost,payment_fees,other_variable_costs,fixed_costs
2026-01-01,1000.00,100.00,10,7,2,3,100.00,300.00,50.00,20.00,30.00,250.00
```

Detailed appointments:

```csv
date,gross_revenue,refunds,bookings,completed,cancelled,ad_spend,variable_cost,other_variable_costs,fixed_costs
2026-01-01,100.00,10.00,10,6,3,20.00,30.00,5.00,25.00
```

Original formats are also accepted:

- E-commerce: `date,revenue,orders,ad_spend,cost_of_goods`.
- Appointments: `date,revenue,bookings,completed,ad_spend,variable_cost`.
- The previous detailed formats without `fixed_costs` remain supported, but operating profit is flagged as having incomplete fixed-cost coverage.

`fixed_costs` is the portion of rent, subscriptions, salaries, and similar fixed expenses allocated to that date. Allocate a monthly fixed cost across the relevant dates, or record it on its posting date; do not repeat the full monthly amount on every row. The platform does not infer allocations.

Use one complete header format per file, in any column order. ISO dates must be unique within the file. Money must be finite, nonnegative, at most 1,000,000,000 per field, and have at most two decimal places. Counts must be whole, nonnegative numbers no greater than 1,000,000,000. Imports are limited to 2 MB and 10,000 rows. Validation of all rows happens before saving; reimporting a date replaces its data atomically within that workspace.

## Outcome definitions

Counts in a row describe the same order or booking cohort; do not mix orders placed that day with fulfillment of orders from other days. Reimport the cohort's row to update its outcomes.

- **Fulfilled** and **cancelled** orders are exclusive. Their sum cannot exceed total orders; the remainder can be pending.
- **Delayed** is a timing flag. It may overlap fulfilled orders (delivered late) or pending orders. It cannot overlap cancelled orders, so delayed + cancelled cannot exceed total orders. Do not add all three statuses together as exclusive buckets. Each individual count must also be at most total orders.
- **Completed** and **cancelled** appointments are exclusive; their sum cannot exceed bookings. Remaining bookings have no reported final outcome.
- Refund money does not provide a product return count and does not change these order-status definitions.

## KPI definitions

| KPI | Definition |
| --- | --- |
| `net_revenue` / `revenue` | Gross sales revenue before refunds minus refunds recorded in the period |
| `variable_costs` | E-commerce: goods + fulfillment + payment fees + other variable costs; appointments: variable cost + other variable costs |
| `estimated_profit` | Net revenue − ad spend − reported variable costs; an estimate of contribution profit |
| `estimated_operating_profit` | Estimated contribution profit − reported fixed costs; a broader operating estimate, not accounting net profit |
| `refund_revenue_percentage` | Refund money / gross revenue × 100; replaces the incorrect `return_rate` name |
| `fulfillment_rate` | Sum of fulfilled orders / sum of total orders × 100 |
| `cancellation_rate` | Sum of cancelled orders or appointments / sum of total orders or bookings × 100 |
| `completion_rate` | Completed appointments / bookings × 100 |
| `average_order_value` | E-commerce net revenue / orders |
| `unattributed_revenue_ad_spend_ratio` | Net revenue / ad spend; uses total business revenue without campaign attribution and must not be read as attributable advertising return |

Rates with a zero denominator are `null`. Fulfillment and cancellation rates are also `null` if any selected row lacks the corresponding outcome field, including mixed legacy/detailed periods. Available outcome counts are observed sums; they may be partial when legacy rows are included.

Refunds can relate to earlier sales, so they may exceed gross revenue for a day or selected period. Net revenue and estimated profit can be negative; the chart supports negative net revenue. A refund percentage above 100% is possible and does not mean more than 100% of products were returned.

Legacy and previous detailed imports lack one or more cost fields. Omitted money is treated as zero for contribution-profit arithmetic and disclosed through `data_quality`, a rule finding, and the dashboard warning. `estimated_profit` remains contribution profit for compatibility. `estimated_operating_profit` is `null` unless every selected row uses the latest schema with fixed costs; when complete, it subtracts reported fixed costs. Both exclude taxes and unreported expenses; neither is accounting net profit or proof of marketing attribution. Monetary totals use decimal arithmetic; API money and rates are returned as JSON numbers.

## Reporting periods

`GET /api/dashboard?start_date=2026-01-01&end_date=2026-01-31` filters dates inclusively inside the authenticated workspace. Supply both dates, ordered, with a maximum of 366 calendar days. With no dates, the range spans the first and last imported row.

`reporting_period` reports requested bounds, observed days, calendar days, missing days, and completeness. An empty range is explicitly incomplete; missing dates are not zero-sales observations. The older `period_start`/`period_end` fields describe observed bounds. KPI totals use only rows in the selected period. Weekly net-revenue diagnostics require two consecutive fully observed Monday–Sunday weeks; a Sunday endpoint includes that just-completed week, while a later partial week is excluded.

## Verification

See [current verification results](VERIFICATION.md). The financial API and CORS regression tests use isolated databases. Migration 0006 is tested on both SQLite and PostgreSQL; standalone PostgreSQL coverage does not establish full-chain pgvector verification.
