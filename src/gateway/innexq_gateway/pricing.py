"""Versioned pricing arithmetic and Phase 1 authority policy.

Identity verification and role mapping belong to the controller. Callers must not
accept ``actor_scenario_role`` from an agent or an approval request payload.
An authorized result is a policy assessment, never executable authorization.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext

from innexq_contracts import AuthorityResult, AuthorityVerdict

TOOL_VERSION = "1.0.0"
RULE_ID = "discount-authority"
RULE_VERSION = "2026-08-15"
ACCOUNT_MANAGER_LIMIT = Decimal("8.00")
_CENT = Decimal("0.01")
_HUNDRED = Decimal("100")


class PricingInputError(ValueError):
    """Untrusted pricing input cannot be evaluated safely."""


@dataclass(frozen=True)
class PricingResult:
    """Exact commercial values with an explicit currency and policy requirement."""

    annual_value: Decimal
    discount_percent: Decimal
    discount_amount: Decimal
    discounted_annual_value: Decimal
    currency: str
    required_scenario_role: str
    tool_version: str = TOOL_VERSION
    rule_id: str = RULE_ID
    rule_version: str = RULE_VERSION

    def as_dict(self) -> dict[str, str]:
        """Use decimal strings on JSON boundaries to preserve financial precision."""
        return {
            "annual_value": str(self.annual_value),
            "discount_percent": str(self.discount_percent),
            "discount_amount": str(self.discount_amount),
            "discounted_annual_value": str(self.discounted_annual_value),
            "currency": self.currency,
            "required_scenario_role": self.required_scenario_role,
            "tool_version": self.tool_version,
            "rule_id": self.rule_id,
            "rule_version": self.rule_version,
        }


def _decimal(value: Decimal | str, field: str) -> Decimal:
    # Floating point, booleans and implicit coercion are deliberately unsupported.
    if not isinstance(value, Decimal | str):
        raise PricingInputError(f"{field} must be a Decimal or decimal string")
    if isinstance(value, str) and (not value or len(value) > 128 or value != value.strip()):
        raise PricingInputError(f"{field} must be a bounded decimal string without whitespace")
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise PricingInputError(f"{field} is not a decimal") from error
    if not parsed.is_finite() or parsed < 0:
        raise PricingInputError(f"{field} must be finite and nonnegative")
    # Representation limits prevent pathological numeric inputs; not a business cap.
    if parsed.adjusted() > 27 or len(parsed.as_tuple().digits) > 64:
        raise PricingInputError(f"{field} exceeds supported numeric precision")
    with localcontext() as context:
        context.prec = 64
        try:
            rounded = parsed.quantize(_CENT, rounding=ROUND_HALF_UP)
        except InvalidOperation as error:
            raise PricingInputError(f"{field} exceeds supported numeric precision") from error
    if rounded != parsed:
        raise PricingInputError(f"{field} must have at most two fractional decimal places")
    # Normalize signed zero so policy and manifest values serialize identically.
    return rounded.copy_abs() if rounded.is_zero() else rounded


def _discount(value: Decimal | str) -> Decimal:
    discount = _decimal(value, "discount_percent")
    if discount > _HUNDRED:
        raise PricingInputError("discount_percent cannot exceed 100")
    return discount


def calculate_pricing(
    annual_value: Decimal | str,
    discount_percent: Decimal | str,
    *,
    currency: str = "EUR",
) -> PricingResult:
    """Price one annual renewal; cent rounding is explicit and reproducible.

    Net annual value rounds half up to cents. Discount amount is the difference
    from the original value, so the two reported amounts always reconcile.
    Values above 8% can be calculated, but cannot be approved in Phase 1.
    """
    if currency != "EUR":
        raise PricingInputError("Phase 1 supports EUR only")
    annual = _decimal(annual_value, "annual_value")
    if annual == 0:
        raise PricingInputError("annual_value must be positive")
    discount = _discount(discount_percent)
    with localcontext() as context:
        context.prec = 64
        net = (annual * (_HUNDRED - discount) / _HUNDRED).quantize(_CENT, rounding=ROUND_HALF_UP)
        discount_amount = annual - net
    return PricingResult(
        annual_value=annual,
        discount_percent=discount,
        discount_amount=discount_amount,
        discounted_annual_value=net,
        currency=currency,
        required_scenario_role=(
            "account_manager" if discount <= ACCOUNT_MANAGER_LIMIT else "operations_manager"
        ),
    )


def check_authority(
    discount_percent: Decimal | str,
    actor_scenario_role: str | None,
) -> AuthorityResult:
    """Evaluate the trusted mapped role; exception approval is disabled in Phase 1."""
    discount = _discount(discount_percent)
    required_role = "account_manager" if discount <= ACCOUNT_MANAGER_LIMIT else "operations_manager"
    if actor_scenario_role not in ("account_manager", "operations_manager"):
        verdict = AuthorityVerdict.UNAUTHORIZED
    elif discount > ACCOUNT_MANAGER_LIMIT:
        verdict = AuthorityVerdict.ESCALATION_REQUIRED
    elif actor_scenario_role == "account_manager":
        verdict = AuthorityVerdict.AUTHORIZED
    else:
        # Do not invent a role inheritance hierarchy for the minimal slice.
        verdict = AuthorityVerdict.UNAUTHORIZED
    return AuthorityResult(
        verdict=verdict,
        actor_scenario_role=actor_scenario_role or "unmapped",
        required_scenario_role=required_role,
        rule_id=RULE_ID,
        rule_version=RULE_VERSION,
    )
