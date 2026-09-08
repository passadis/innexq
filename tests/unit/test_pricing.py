"""Financial reconciliation and fail-closed authority tests for the Phase 1 gateway."""

from decimal import ROUND_DOWN, Decimal, localcontext
from typing import Any

import pytest
from innexq_contracts import AuthorityVerdict
from innexq_gateway import PricingInputError, calculate_pricing, check_authority


def test_fabrikam_eight_percent_is_exact_and_authorized() -> None:
    price = calculate_pricing("180000.00", "8")
    assert price.discounted_annual_value == Decimal("165600.00")
    assert price.discount_amount == Decimal("14400.00")
    assert price.required_scenario_role == "account_manager"
    assert price.as_dict()["discounted_annual_value"] == "165600.00"
    assert check_authority("8", "account_manager").verdict == AuthorityVerdict.AUTHORIZED


@pytest.mark.parametrize("role", ["account_manager", "operations_manager"])
@pytest.mark.parametrize("discount", ["8.01", "12", "100"])
def test_exception_never_becomes_executable_in_phase_one(role: str, discount: str) -> None:
    price = calculate_pricing("180000", discount)
    authority = check_authority(discount, role)
    assert authority.verdict == AuthorityVerdict.ESCALATION_REQUIRED
    assert authority.required_scenario_role == price.required_scenario_role == "operations_manager"


@pytest.mark.parametrize("role", [None, "", "admin", "Account_Manager", "operations_manager"])
def test_only_explicit_account_manager_role_can_pass(role: str | None) -> None:
    assert check_authority("8", role).verdict == AuthorityVerdict.UNAUTHORIZED


def test_unknown_role_stays_unauthorized_for_exception() -> None:
    assert check_authority("12", None).verdict == AuthorityVerdict.UNAUTHORIZED


@pytest.mark.parametrize(
    "value",
    ["NaN", "sNaN", "Infinity", "-Infinity", "-1", "bad", "", " 8", "8 ", "0.001", "1e99"],
)
def test_malformed_financial_input_fails_closed(value: str) -> None:
    with pytest.raises(PricingInputError):
        calculate_pricing(value, "8")
    with pytest.raises(PricingInputError):
        calculate_pricing("180000", value)
    with pytest.raises(PricingInputError):
        check_authority(value, "account_manager")


@pytest.mark.parametrize("value", [True, 8, 8.0, None, {}, []])
def test_no_lossy_or_implicit_numeric_coercion(value: Any) -> None:
    with pytest.raises(PricingInputError):
        calculate_pricing("180000", value)


def test_zero_annual_value_and_out_of_range_discount_are_invalid() -> None:
    with pytest.raises(PricingInputError):
        calculate_pricing("0", "8")
    with pytest.raises(PricingInputError):
        calculate_pricing("180000", "100.01")
    with pytest.raises(PricingInputError):
        check_authority("100.01", "account_manager")


def test_currency_cannot_silently_change() -> None:
    with pytest.raises(PricingInputError):
        calculate_pricing("180000", "8", currency="USD")


def test_net_rounding_reconciles_and_ignores_ambient_decimal_context() -> None:
    with localcontext() as context:
        context.prec = 3
        context.rounding = ROUND_DOWN
        price = calculate_pricing(Decimal("1.05"), Decimal("50"))
    assert price.discounted_annual_value == Decimal("0.53")
    assert price.discount_amount == Decimal("0.52")
    assert price.discounted_annual_value + price.discount_amount == price.annual_value


def test_zero_discount_preserves_price_and_normalizes_signed_zero() -> None:
    price = calculate_pricing("180000", "-0.00")
    assert price.discounted_annual_value == price.annual_value
    assert price.as_dict()["discount_percent"] == "0.00"
    assert check_authority("0", "account_manager").verdict == AuthorityVerdict.AUTHORIZED


def test_excessive_representation_is_rejected() -> None:
    for value in ("1" * 129, Decimal("0." + "0" * 10 + "1" * 65)):
        with pytest.raises(PricingInputError):
            calculate_pricing(value, "8")
