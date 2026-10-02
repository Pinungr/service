// Money is whole paise (an integer) everywhere. These helpers only display and parse it;
// they never compute totals, balances or charges — the backend does that.

const GROUP = new Intl.NumberFormat('en-IN');

/** 125050 → "₹1,250.50". Exact integer arithmetic, never floating point. */
export function formatPaise(paise: number | null | undefined): string {
  if (paise === null || paise === undefined) return '—';
  const negative = paise < 0;
  const abs = Math.abs(Math.trunc(paise));
  const rupees = Math.floor(abs / 100);
  const fraction = String(abs % 100).padStart(2, '0');
  return (negative ? '-' : '') + '₹' + GROUP.format(rupees) + '.' + fraction;
}

/** "1,250.5" → 125050. Returns null for anything that is not an amount. */
export function parseRupees(text: string): number | null {
  const cleaned = text.replace(/[₹,\s]/g, '');
  if (cleaned === '') return 0;
  const match = /^(-)?(\d{1,10})(?:\.(\d{0,2}))?$/.exec(cleaned);
  if (!match) return null;
  const whole = Number(match[2]);
  const fraction = Number((match[3] ?? '').padEnd(2, '0'));
  const value = whole * 100 + fraction;
  return match[1] ? -value : value;
}

/** 125050 → "1250.50", for prefilling an editable amount field. */
export function paiseToText(paise: number | null | undefined): string {
  if (!paise) return '0';
  const abs = Math.abs(paise);
  return (paise < 0 ? '-' : '') + Math.floor(abs / 100) + '.' + String(abs % 100).padStart(2, '0');
}
