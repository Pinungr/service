// Timestamps arrive as ISO-8601 from the backend and are shown in the SHOP's timezone,
// never the browser's, so an event means the same moment on every computer.

let shopZone = 'Asia/Kolkata';

export function setShopTimezone(zone: string | undefined) {
  if (zone) shopZone = zone;
}

/** "2026-10-02T09:15:00+00:00" → "02 Oct 2026, 2:45 pm" in the shop's zone. */
export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—';
  const date = new Date(value.endsWith('Z') || /[+-]\d\d:\d\d$/.test(value) ? value : value + 'Z');
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('en-IN', {
    timeZone: shopZone, day: '2-digit', month: 'short', year: 'numeric', hour: 'numeric', minute: '2-digit',
  }).format(date);
}

/** A calendar date ("2026-10-02") is a date, not a moment: no timezone conversion. */
export function formatDate(value: string | null | undefined): string {
  if (!value) return '—';
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!match) return value;
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  return `${match[3]} ${months[Number(match[2]) - 1]} ${match[1]}`;
}

/** Today's date where the shop is, for date-field defaults. */
export function shopToday(): string {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: shopZone, year: 'numeric', month: '2-digit', day: '2-digit' })
    .formatToParts(new Date());
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? '';
  return `${get('year')}-${get('month')}-${get('day')}`;
}

export function looksLikeTimestamp(value: unknown): value is string {
  return typeof value === 'string' && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(value);
}
