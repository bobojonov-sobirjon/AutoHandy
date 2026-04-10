"""WGS84 lat/lon Decimal limits — must stay in sync with CustomUser, Order, Master model fields."""

# Integer part needs room for longitude −180…180 (three digits); fractional precision matches models.
WGS84_COORD_DECIMAL_KWARGS = {
    'max_digits': 22,
    'decimal_places': 18,
}
