from datetime import datetime, timezone, date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import re
import unicodedata

#: The shop's own timezone. Timestamps are stored in UTC and only ever converted for
#: display and for "is this overdue today" comparisons. `Database` publishes the
#: configured value here at startup so there is one source of truth and no hardcoded
#: UTC offset anywhere in the application.
DEFAULT_TIMEZONE = 'Asia/Kolkata'
_timezone = DEFAULT_TIMEZONE


class RuleError(ValueError):
    """A business validation error safe to show to staff."""


def use_timezone(name):
    global _timezone
    try:
        ZoneInfo(name or DEFAULT_TIMEZONE)
    except (ZoneInfoNotFoundError, ValueError):
        raise RuleError('Unknown timezone: ' + str(name))
    _timezone = name or DEFAULT_TIMEZONE
    return _timezone


def zone():
    try:
        return ZoneInfo(_timezone)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(DEFAULT_TIMEZONE)


def timezone_name():
    return _timezone


def today():
    """The current date where the shop actually is, for due-date comparisons."""
    return datetime.now(zone()).date().isoformat()


def local_time(value):
    if not value:
        return 'Not recorded'
    try:
        return datetime.fromisoformat(value).astimezone(zone()).strftime('%d %b %Y, %I:%M %p')
    except ValueError:
        return value


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


# ---- custody vocabulary -------------------------------------------------
# A custody location answers "who is responsible for this item right now".
#
#   staff:<user id>           an authorized staff/admin user is holding it
#   technician:<user id>      a technician user is holding it
#   technician:master-<id>    a directory technician is holding it
#   vendor: / centre:         an external repairer has it
#   transit:<carrier>         a carrier is moving it
#   customer                  it is back with its owner
#   exception:<reason>        it is lost, written off or otherwise resolved
#
# There is no storage custodian. Every item in the shop is the responsibility of a named
# person, so `shop:<place>` is not a custody value and is rejected wherever it appears.
STAFF_CUSTODY = ('staff:', 'technician:')
SHOP_CUSTODY = STAFF_CUSTODY
AWAY_CUSTODY = ('vendor:', 'centre:', 'transit:')


def in_shop(location):
    """Is the item in the shop's own possession, i.e. held by one of our people?"""
    return str(location or '').startswith(SHOP_CUSTODY)


def is_away(location):
    """Is the item with an external repairer or a carrier?"""
    return str(location or '').startswith(AWAY_CUSTODY)


def custody_kind(location):
    location = str(location or '')
    if location == 'customer':
        return 'customer'
    return location.split(':', 1)[0] if ':' in location else location


def staff_custody(user_id):
    return 'staff:' + str(int(user_id))


def sql_in_shop(column):
    """The same 'in the shop's possession' test, for use inside a SQL predicate."""
    return '(' + ' OR '.join(f"{column} LIKE '{prefix}%'" for prefix in SHOP_CUSTODY) + ')'


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
MASTER_KINDS = ["category", "brand", "model", "service", "accessory", "technician", "vendor", "supplier", "centre", "transporter", "transport_method", "payment_method"]
