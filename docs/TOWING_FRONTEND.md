# Towing — simplified pricing (no minimum fee)

**Formula:** `total = base_fee + (distance_miles × price_per_mile)`

**Distance:** pickup → drop-off coordinates (automatic), or explicit `distance_miles`.

---

## Master workshop — GET response

Each `services[]` item now includes **`examples`** (10 / 20 / 50 miles):

```json
{
  "pricing_formula": "total = base_fee + (distance_miles × price_per_mile)",
  "services": [
    {
      "service_type": "local",
      "base_fee": "100.00",
      "price_per_mile": "3.00",
      "examples": [
        {
          "distance_miles": "10.00",
          "total_price": "130.00",
          "label": "10.00 mi: $100.00 + (10.00 × $3.00) = $130.00"
        },
        {
          "distance_miles": "20.00",
          "total_price": "160.00",
          "label": "20.00 mi: $100.00 + (20.00 × $3.00) = $160.00"
        },
        {
          "distance_miles": "50.00",
          "total_price": "250.00",
          "label": "50.00 mi: $100.00 + (50.00 × $3.00) = $250.00"
        }
      ]
    }
  ]
}
```

Show `examples[].label` under Base fee / Per mile fields. **Remove Minimum fee from UI.**

## Master PUT body

Only `base_fee`, `price_per_mile`, `is_active` — no `minimum_fee`.

## Driver estimate

Response includes `distance_source`: `pickup_to_dropoff` or `explicit_miles`.

Pricing breakdown has no `minimum_fee`.

## Breaking change

- `minimum_fee` removed from `MasterTowingPricing` and API.
- Old orders may still have `towing_minimum_fee` in DB (ignored for display on new orders).
