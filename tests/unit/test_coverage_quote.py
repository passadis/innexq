"""Deterministic renewal quote arithmetic tests."""

from __future__ import annotations

from decimal import Decimal

import pytest
from innexq_gateway.coverage import calculate_renewal_quote
from innexq_gateway.pricing import PricingInputError


def test_quote_reconciles_and_is_reproducible() -> None:
    first = calculate_renewal_quote("8500.00")
    second = calculate_renewal_quote(Decimal("8500.00"))
    assert first == second
    assert first.base_amount == "8500.00"
    assert first.vat_rate_percent == "24.00"
    assert first.vat_amount == "2040.00"
    assert first.total_amount == "10540.00"
    assert first.currency == "EUR"
    assert first.coverage_months == 12


def test_quote_rounds_vat_half_up_to_cents() -> None:
    # 104.27 * 24% = 25.0248 -> 25.02; 10.31 * 24% = 2.4744 -> 2.47
    assert calculate_renewal_quote("104.27").vat_amount == "25.02"
    assert calculate_renewal_quote("10.31").vat_amount == "2.47"
    # 56.25 * 24% = 13.50 exactly
    quote = calculate_renewal_quote("56.25")
    assert quote.vat_amount == "13.50"
    assert quote.total_amount == "69.75"


def test_quote_rejects_unsupported_inputs() -> None:
    with pytest.raises(PricingInputError, match="EUR only"):
        calculate_renewal_quote("100.00", currency="USD")
    with pytest.raises(PricingInputError, match="positive"):
        calculate_renewal_quote("0.00")
    with pytest.raises(PricingInputError, match="two fractional"):
        calculate_renewal_quote("100.005")
    with pytest.raises(PricingInputError, match="not a decimal"):
        calculate_renewal_quote("one hundred")
    with pytest.raises(PricingInputError):
        calculate_renewal_quote(100.0)  # type: ignore[arg-type]  # floats are refused
