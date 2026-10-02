import { FormEvent, ReactNode, useMemo, useState } from 'react';
import type { FormField, Option } from '../api/types';
import { paiseToText, parseRupees } from '../shared/money';
import { ContactSelector } from './ContactSelector';
import { TransportField, TransportValue } from './TransportField';

/**
 * Renders a form from field descriptions (from the backend for lifecycle actions, or
 * from a feature module) and returns typed values. It decides nothing about the
 * business: which fields exist and what is valid are the backend's answers.
 */
export function FieldForm({ fields, onSubmit, submitLabel = 'Save', busy = false, error, footer, onCancel, compact = false }: {
  fields: FormField[];
  onSubmit: (values: Record<string, any>) => void;
  submitLabel?: string;
  busy?: boolean;
  error?: ReactNode;
  footer?: ReactNode;
  onCancel?: () => void;
  compact?: boolean;
}) {
  const initial = useMemo(() => initialValues(fields), [fields]);
  const [values, setValues] = useState<Record<string, any>>(initial);
  const [problem, setProblem] = useState('');
  const set = (key: string, value: unknown) => setValues((v) => ({ ...v, [key]: value }));
  const visible = fields.filter((f) => isVisible(f, values));

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const out: Record<string, any> = {};
    for (const field of visible) {
      if (field.type === 'info') continue;
      let value = values[field.key];
      if (field.type === 'money') {
        const parsed = parseRupees(String(value ?? ''));
        if (parsed === null) { setProblem(`Enter ${field.label.toLowerCase()} as an amount, for example 1250.50.`); return; }
        value = parsed;
      }
      if (field.type === 'number') value = value === '' || value === undefined ? null : Number(value);
      if (field.required && (value === '' || value === null || value === undefined || value === false || (Array.isArray(value) && !value.length))) {
        setProblem(`${field.label} is required.`);
        return;
      }
      out[field.key] = value;
    }
    setProblem('');
    onSubmit(out);
  };

  return (
    <form className="form" onSubmit={submit} noValidate>
      <div className={compact ? 'form' : 'form-grid'}>
        {visible.map((field) => (
          <div key={field.key} style={{ gridColumn: wide(field) ? '1 / -1' : undefined }}>
            <Field field={field} value={values[field.key]} onChange={(v) => set(field.key, v)} />
          </div>
        ))}
      </div>
      {problem && <div className="error" role="alert">{problem}</div>}
      {error}
      <div className="row">
        <button type="submit" className="primary" disabled={busy}>{busy ? 'Saving…' : submitLabel}</button>
        {onCancel && <button type="button" onClick={onCancel}>Cancel</button>}
        {footer}
      </div>
    </form>
  );
}

function wide(field: FormField) {
  return ['textarea', 'info', 'contact', 'transport', 'items', 'return_items', 'route'].includes(field.type);
}

export function isVisible(field: FormField, values: Record<string, any>): boolean {
  if (!field.show_if) return true;
  return field.show_if.equals.includes(values[field.show_if.field]);
}

export function initialValues(fields: FormField[]): Record<string, any> {
  const values: Record<string, any> = {};
  for (const field of fields) {
    const d = field.default;
    switch (field.type) {
      case 'check': values[field.key] = Boolean(d); break;
      case 'money': values[field.key] = typeof d === 'number' ? paiseToText(d) : d ?? '0'; break;
      case 'items': values[field.key] = Array.isArray(d) ? d : []; break;
      case 'return_items':
        values[field.key] = (field.options ?? []).map((o) => ({ item_id: o.value, expected: o.expected ?? 1, received: o.expected ?? 1, discrepancy: '', notes: '' }));
        break;
      case 'transport': values[field.key] = { mode: d?.mode ?? 'COURIER', service_id: null, fields: {} }; break;
      case 'select': values[field.key] = d ?? (field.options?.length === 1 ? field.options[0].value : ''); break;
      default: values[field.key] = d ?? '';
    }
  }
  return values;
}

function Label({ field }: { field: FormField }) {
  return <span className={'label' + (field.required ? ' required' : '')}>{field.label}</span>;
}

export function Field({ field, value, onChange }: { field: FormField; value: any; onChange: (value: any) => void }) {
  switch (field.type) {
    case 'info':
      return <div><div className="small muted" style={{ fontWeight: 600, marginBottom: 4 }}>{field.label}</div><div className="info-box">{String(field.default ?? '')}</div></div>;
    case 'check':
      return <label className="check"><input type="checkbox" checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} /><span className={field.required ? 'required' : ''}>{field.label}</span></label>;
    case 'textarea':
      return <label className="field"><Label field={field} /><textarea aria-label={field.label} value={value ?? ''} onChange={(e) => onChange(e.target.value)} /></label>;
    case 'date':
      return <label className="field"><Label field={field} /><input aria-label={field.label} type="date" value={value ?? ''} onChange={(e) => onChange(e.target.value)} /></label>;
    case 'time':
      return <label className="field"><Label field={field} /><input aria-label={field.label} type="time" value={value ?? ''} onChange={(e) => onChange(e.target.value)} /></label>;
    case 'number':
      return <label className="field"><Label field={field} /><input aria-label={field.label} type="number" value={value ?? ''} onChange={(e) => onChange(e.target.value)} /></label>;
    case 'money':
      return <label className="field"><Label field={field} /><input aria-label={field.label} inputMode="decimal" value={value ?? ''} onChange={(e) => onChange(e.target.value)} placeholder="0.00" /></label>;
    case 'select':
      return (
        <label className="field"><Label field={field} />
          <select aria-label={field.label} value={value ?? ''} onChange={(e) => onChange(optionValue(field.options, e.target.value))}>
            {!(field.options ?? []).some((o) => o.value === '') && <option value="">Choose…</option>}
            {(field.options ?? []).map((o) => <option key={String(o.value)} value={String(o.value)} disabled={o.disabled}>{o.label}</option>)}
          </select>
        </label>
      );
    case 'route':
      return (
        <fieldset className="stack" style={{ border: 0, padding: 0, margin: 0 }}>
          <legend className="label required" style={{ fontWeight: 600, marginBottom: 6 }}>{field.label}</legend>
          <div className="grid4">
            {(field.options ?? []).map((o) => (
              <button type="button" key={String(o.value)} disabled={o.disabled} title={o.reason || o.label}
                      className={value === o.value ? 'primary' : ''} style={{ minHeight: 60 }} onClick={() => onChange(o.value)}>
                {o.label}{o.disabled && o.reason ? <div className="small" style={{ fontWeight: 400 }}>{o.reason}</div> : null}
              </button>
            ))}
          </div>
        </fieldset>
      );
    case 'contact':
      return (
        <div className="field"><Label field={field} />
          <ContactSelector kind={field.kind as any} jobId={field.job_id} value={value || null} onChange={(id) => onChange(id)} />
        </div>
      );
    case 'transport':
      return <TransportField value={value as TransportValue} onChange={onChange} />;
    case 'items':
      return (
        <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
          <legend className={'label' + (field.required ? ' required' : '')} style={{ fontWeight: 600, marginBottom: 6 }}>{field.label}</legend>
          {(field.options ?? []).map((o) => {
            const selected: unknown[] = value ?? [];
            return (
              <label key={String(o.value)} className="check" style={{ fontWeight: 400 }}>
                <input type="checkbox" checked={selected.includes(o.value)}
                       onChange={(e) => onChange(e.target.checked ? [...selected, o.value] : selected.filter((v) => v !== o.value))} />
                {o.label}{o.type === 'device' ? <span className="badge info">device</span> : null}
              </label>
            );
          })}
        </fieldset>
      );
    case 'return_items':
      return <ReturnItems field={field} value={value} onChange={onChange} />;
    default:
      return <label className="field"><Label field={field} /><input aria-label={field.label} value={value ?? ''} placeholder={field.placeholder} onChange={(e) => onChange(e.target.value)} /></label>;
  }
}

function optionValue(options: Option<any>[] | undefined, raw: string) {
  const match = (options ?? []).find((o) => String(o.value) === raw);
  return match ? match.value : raw;
}

interface ReturnRow { item_id: number; expected: number; received: number; discrepancy: string; notes: string }

function ReturnItems({ field, value, onChange }: { field: FormField; value: ReturnRow[]; onChange: (v: ReturnRow[]) => void }) {
  const rows = value ?? [];
  const update = (index: number, patch: Partial<ReturnRow>) => onChange(rows.map((r, i) => (i === index ? { ...r, ...patch } : r)));
  return (
    <div>
      <div className="label required" style={{ fontWeight: 600, marginBottom: 6 }}>{field.label}</div>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Item</th><th>Sent</th><th>Received now</th><th>Discrepancy</th><th>Note</th></tr></thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={row.item_id}>
                <td>{field.options?.[index]?.label}</td>
                <td>{row.expected}</td>
                <td style={{ width: 110 }}><input type="number" min={0} max={row.expected} value={row.received}
                                                  onChange={(e) => update(index, { received: Number(e.target.value) })} /></td>
                <td style={{ width: 170 }}>
                  <select value={row.discrepancy} onChange={(e) => update(index, { discrepancy: e.target.value })}>
                    <option value="">No problem</option>
                    {(field.discrepancies ?? []).map((d) => <option key={d.value} value={d.value}>{d.label}</option>)}
                  </select>
                </td>
                <td><input value={row.notes} placeholder="Explain the discrepancy" onChange={(e) => update(index, { notes: e.target.value })} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
