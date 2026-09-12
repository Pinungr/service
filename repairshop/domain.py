from datetime import datetime, timezone, date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
import unicodedata


class RuleError(ValueError):
    """A business validation error safe to show to staff."""


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def money(value):
    if isinstance(value, float):
        raise RuleError("Enter money as decimal text, never a floating-point number.")
    try:
        d = Decimal(str(value))
        if not d.is_finite() or abs(d) > Decimal("9999999999"):
            raise ValueError()
        return int((d * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (ValueError, InvalidOperation):
        raise RuleError("Enter a valid amount in rupees.")


def rupees(paise):
    return f"INR {Decimal(paise or 0) / 100:,.2f}"


def norm(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def phone(value):
    digits = re.sub(r"\D", "", value or "")
    if not digits:
        return ""
    if len(digits) == 10:
        digits = "91" + digits
    if not 8 <= len(digits) <= 15:
        raise RuleError("Enter a valid phone number with country code.")
    return "+" + digits


def day(value):
    if value:
        date.fromisoformat(value)
    return value or None


STAGES = ["received", "diagnosis", "awaiting_estimate", "awaiting_approval", "approved", "ready_dispatch", "under_repair", "waiting_parts", "awaiting_return", "testing", "ready_repaired", "return_unrepaired", "ready_unrepaired", "collected", "closed"]
STAGES += ['inspection', 'warranty_check', 'route_selection', 'external_diagnosis', 'technician_testing', 'final_qc', 'billing']
ROUTES = ["in_house", "third_party", "warranty_centre"]
MASTER_KINDS = ["category", "brand", "model", "service", "accessory", "technician", "vendor", "supplier", "centre", "transporter", "transport_method", "storage", "payment_method"]
