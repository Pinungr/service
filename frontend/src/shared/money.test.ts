import { describe, expect, it } from 'vitest';
import { formatPaise, paiseToText, parseRupees } from './money';
import { formatDate, formatDateTime, setShopTimezone } from './dates';

describe('money is exact integer paise', () => {
  it('parses typed rupees without floating point', () => {
    expect(parseRupees('1,250.50')).toBe(125050);
    expect(parseRupees('0.1')).toBe(10);
    expect(parseRupees('₹ 19.99')).toBe(1999);
    expect(parseRupees('-500')).toBe(-50000);
    expect(parseRupees('')).toBe(0);
    expect(parseRupees('12.345')).toBeNull();
    expect(parseRupees('abc')).toBeNull();
  });

  it('formats paise for display and for editing', () => {
    expect(formatPaise(125050)).toBe('₹1,250.50');
    expect(formatPaise(-1999)).toBe('-₹19.99');
    expect(formatPaise(10000000)).toBe('₹1,00,000.00');
    expect(paiseToText(35000)).toBe('350.00');
    expect(parseRupees(paiseToText(98765))).toBe(98765);
  });
});

describe('dates use the shop timezone, not the browser', () => {
  it('shows an instant in the shop zone and a calendar date unchanged', () => {
    setShopTimezone('Asia/Kolkata');
    expect(formatDateTime('2026-10-02T00:30:00+00:00')).toContain('6:00 am');
    expect(formatDate('2026-10-02')).toBe('02 Oct 2026');
    setShopTimezone('America/New_York');
    expect(formatDateTime('2026-10-02T00:30:00+00:00')).toContain('01 Oct 2026');
    setShopTimezone('Asia/Kolkata');
  });
});
