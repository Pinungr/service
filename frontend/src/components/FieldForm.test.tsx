import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';

afterEach(cleanup);
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { FormField } from '../api/types';
import { FieldForm, initialValues, isVisible } from './FieldForm';
import { JourneyBar } from '../features/repairs/JourneyBar';

const ROUTE_FORM: FormField[] = [
  { key: 'route', label: 'Route', type: 'select', required: true, options: [{ value: 'in_house', label: 'In house' }, { value: 'third_party', label: 'Third party' }] },
  { key: 'reference', label: 'External ticket', type: 'text', show_if: { field: 'route', equals: ['third_party'] } },
  { key: 'amount', label: 'Transport charge', type: 'money', default: 35000 },
  { key: 'note', label: 'Shown info', type: 'info', default: 'Read only' },
];

function renderForm(onSubmit: (v: Record<string, unknown>) => void) {
  return render(<QueryClientProvider client={new QueryClient()}><FieldForm fields={ROUTE_FORM} onSubmit={onSubmit} /></QueryClientProvider>);
}

describe('FieldForm renders exactly what the backend describes', () => {
  it('prefills from defaults and hides fields until their condition holds', () => {
    const values = initialValues(ROUTE_FORM);
    expect(values.amount).toBe('350.00');
    expect(isVisible(ROUTE_FORM[1], values)).toBe(false);
    expect(isVisible(ROUTE_FORM[1], { ...values, route: 'third_party' })).toBe(true);
  });

  it('submits only visible fields, with money as integer paise', () => {
    const onSubmit = vi.fn();
    renderForm(onSubmit);
    expect(screen.queryByLabelText('External ticket')).toBeNull();
    fireEvent.change(screen.getByLabelText('Route'), { target: { value: 'third_party' } });
    fireEvent.change(screen.getByLabelText('External ticket'), { target: { value: 'EXT-77' } });
    fireEvent.change(screen.getByLabelText('Transport charge'), { target: { value: '1,250.50' } });
    fireEvent.click(screen.getByText('Save'));
    expect(onSubmit).toHaveBeenCalledWith({ route: 'third_party', reference: 'EXT-77', amount: 125050 });
  });

  it('refuses an amount that is not money instead of guessing', () => {
    const onSubmit = vi.fn();
    renderForm(onSubmit);
    fireEvent.change(screen.getByLabelText('Route'), { target: { value: 'in_house' } });
    fireEvent.change(screen.getByLabelText('Transport charge'), { target: { value: '12.345' } });
    fireEvent.click(screen.getByText('Save'));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByRole('alert').textContent).toContain('transport charge');
  });

  it('enforces required fields for convenience (the backend still decides)', () => {
    const onSubmit = vi.fn();
    renderForm(onSubmit);
    fireEvent.click(screen.getByText('Save'));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByRole('alert').textContent).toContain('Route is required');
  });
});

describe('JourneyBar', () => {
  it('shows each node with the state the backend reported', () => {
    render(<JourneyBar journey={{
      repair_id: 1, job_number: 'REP-1', version: 3, current_stage: 'inspection', route: 'in_house', route_label: 'X', next_action: 'Inspect',
      nodes: [
        { key: 'received', label: 'Received', status: 'completed', detail: '', current: false, options: [], events: [], action: null },
        { key: 'inspection', label: 'Initial inspection', status: 'current', detail: '', current: true, options: [], events: [], action: null },
        { key: 'awaiting_estimate', label: 'Estimate', status: 'skipped', detail: 'Not required', current: false, options: [], events: [], action: null },
        { key: 'closed', label: 'Closed', status: 'future', detail: '', current: false, options: [], events: [], action: null },
      ],
    }} />);
    const items = screen.getAllByRole('listitem');
    expect(items.map((i) => i.textContent)).toEqual([
      'Received✓ Completed', 'Initial inspection● Action required', 'Estimate— Not applicable', 'Closed○ Upcoming']);
    expect(items[1].getAttribute('aria-current')).toBe('step');
  });
});
