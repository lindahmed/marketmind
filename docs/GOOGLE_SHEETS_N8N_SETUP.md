# Google Sheets ingestion through n8n Cloud

This is the first supported external source path. MarketMind does not connect to Google directly. You own the workflow in n8n Cloud; the workflow reads your sheet and pushes normalized rows to the MarketMind API.

## 1. Create a source credential

1. Deploy the API at an HTTPS address that n8n Cloud can reach. `localhost` and private LAN addresses are not reachable from n8n Cloud.
2. Sign in to the business workspace as an owner and open **Data Sources & Data Quality**.
3. Create a source named for the sheet and enter its Google Sheet ID. The ID is the portion between `/d/` and `/edit` in the sheet URL.
4. Copy the displayed ingestion token immediately. MarketMind stores only its SHA-256 digest and does not display it again.
5. In n8n Cloud, create a **Header Auth** credential:
   - Name: `Authorization`
   - Value: `Bearer <the one-time ingestion token>`

Keep the credential private. Do not put the token in a spreadsheet, Code node, URL, or workflow output. Revoke it from the data-source page if it is exposed. Use **Rotate token** to issue a replacement; the old token stops working and the new token is shown once.

## 2. Add these nodes manually in n8n Cloud

1. **Schedule Trigger** (or a manual trigger for the first run).
2. **Google Sheets** node, operation **Get Row(s)**. Select the spreadsheet and tab. Read order/payment, fulfillment/cancellation, refund, marketing spend, and expense rows. For appointment businesses, read appointment outcomes instead of order outcomes.
3. **Code** node (JavaScript), map the selected rows into one request object with `request_id` and `records`. Generate a new stable `request_id` per changed sync batch, and reuse it only when retrying the identical payload. Preserve each row's stable source event ID and sheet row locator. Keep a prior source ID list so deleted rows can be sent explicitly.
4. **HTTP Request** node:
   - Method: `POST`
   - URL: `https://<your-marketmind-api>/api/integrations/google-sheets/<source-id>/ingest`
   - Authentication: select the Header Auth credential from step 1
   - Send body: JSON, using the Code node's request object
   - Timeout: at least 60 seconds for a batch of up to 5,000 events
5. Optional **IF** node after the HTTP Request to route non-2xx errors or responses with a nonzero conflict/missing count to your manual review/notification path. Do not treat `accepted_count` as evidence of a marketing effect.

There is no n8n webhook-trigger node in this direction: the workflow pushes records to the MarketMind endpoint. No workflow JSON is generated or imported by MarketMind.

## 3. Canonical request shape

```json
{
  "request_id": "sheet-snapshot-2026-10-12-001",
  "records": [
    {
      "source_event_id": "payments-row-42",
      "event_type": "payment",
      "occurred_at": "2026-10-12T14:32:00Z",
      "entity_id": "order-8421",
      "amount": "89.50",
      "currency": "USD",
      "status": "captured",
      "campaign_id": "fall-email-1",
      "channel": "email",
      "record_locator": "Payments!A42"
    }
  ]
}
```

`source_event_id` is the stable row key. Keep it when correcting a row's amount, status, or date; the old version remains in the event history and only the corrected version contributes to current reporting. Lifecycle rows (`order`, `fulfillment`, `cancellation`, `appointment_outcome`) also match by their stable business `entity_id`, even when timestamps or sheet row IDs change. For appointment outcomes, also send `booked_at`, `scheduled_at`, and `completed_at` as ISO timestamps when available. MarketMind counts bookings on booked date, scheduled appointments on scheduled date, and completions on completion date; `occurred_at` remains the source event/update time. For `payment`, `refund`, `expense`, and `marketing_spend`, use a unique transaction/ledger ID as `entity_id` where possible. Multiple partial payments against one order must have different payment IDs. An ambiguous same-entity record from another source is held for owner review rather than added to totals.

To report a deleted source row, include its IDs in `deleted_source_event_ids`. This appends a current-state tombstone and excludes the row from current KPIs while preserving the original event and import provenance. The import history reports the deleted count. Do not delete a row from the sheet and assume MarketMind can infer its old ID from a normal row read. For snapshot syncs, compare the current sheet IDs against the IDs from the previous sync and explicitly submit the missing IDs as deletions.

Financial source coverage must be explicit. Include `coverage` entries for each calendar day and kind the sheet fully covers, including days with no transactions. A complete no-spend day is represented by `marketing_spend` coverage with `complete: true` and no spend row. A day without coverage is unknown; profit and related financial ratios are withheld when required source coverage is incomplete. Example:

```json
{
  "request_id": "sheet-coverage-2026-10-12",
  "records": [],
  "coverage": [
    {"day": "2026-10-12", "data_kind": "payments", "complete": true},
    {"day": "2026-10-12", "data_kind": "refunds", "complete": true},
    {"day": "2026-10-12", "data_kind": "marketing_spend", "complete": true},
    {"day": "2026-10-12", "data_kind": "variable_costs", "complete": true},
    {"day": "2026-10-12", "data_kind": "fixed_costs", "complete": true}
  ]
}
```

You can send a coverage-only or deletion-only batch. Use `data_kind` values `payments`, `refunds`, `marketing_spend`, `variable_costs`, `fixed_costs`, `orders`, `fulfillment`, or `appointments`.

`event_type` may be `order`, `fulfillment`, `cancellation`, `refund`, `payment`, `marketing_spend`, `appointment_outcome`, or `expense`. Each row needs a stable `source_event_id`, an ISO timestamp, and an `entity_id` where the event contract requires one. Payment status must be `captured`, `pending`, `failed`, or `refunded`. Appointment outcome status must be `booked`, `completed`, `cancelled`, or `no_show`. Expense rows set `cost_category` to `variable` or `fixed`; all supplied currencies must match the workspace currency. Schema-invalid requests or mismatched currencies are rejected with HTTP 422. A structurally valid row missing a required event field is retained as an incomplete review item and excluded from analytics.

For e-commerce, send one `order` per order, a `payment` only for each payment, and separate fulfillment, cancellation, and refund events. `order.amount` is recorded as order data; only captured `payment` amounts enter gross revenue, so do not send a payment twice. For appointment businesses, send one `appointment_outcome` per booking. Expense and marketing spend rows should use stable entity IDs such as a ledger transaction ID or a campaign/day key.

The response includes import status and received/accepted/duplicate/conflict/missing counts. Exact cross-source matches are duplicates. Conflicts and incomplete records remain visible on the review page. An owner can resolve a conflict through `POST /api/data-sources/conflicts/{event_id}/resolve` using `accept_incoming`, `retain_existing`, or `mark_duplicate`; each decision records the owner, note, selected event, and both provenance snapshots. Corrections and deletions never erase historical rows. Reusing the same `request_id` with the same payload is idempotent; using it with changed content returns HTTP 409. A database uniqueness guard prevents two concurrent imports from making the same current entity key active.

## Financial treatment and campaign limits

Accepted reconciled events feed financial KPIs for dates without a CSV summary. If a CSV row already exists on a date with event data, the CSV row is retained and the overlap date is flagged for review; event batches can be partial and the platform does not silently replace an aggregate with incomplete fields. Captured payment amounts, refunds, spend, and classified expenses feed the existing financial KPIs on event-supplied dates. E-commerce order and fulfillment counts, and appointment booking/completion/cancellation counts, are industry-specific. Data Quality and dashboard coverage notes show absent event categories; a connected sheet is not assumed to contain every required ledger.

Campaign IDs and channels are source labels. MarketMind may display captured payment totals with a recorded campaign ID, but it does not assign campaign causality, calculate attributable ROAS, or assign unmatched payments to ads. Reconciliation uses stable source row IDs and business entity IDs; timestamps describe when an event happened and are not the sole match key.

## First-run check

Run the workflow once manually. Confirm the HTTP response is `200`, then refresh **Data Sources & Data Quality** and check sync time and row counts. Send the exact same request again to confirm the response marks it replayed without adding events. To exercise review, use a second source for the same business entity with one changed amount; confirm the new record appears as a conflict and dashboard totals remain based on the first accepted record. Do not test against production financial data until you have a restorable backup.
