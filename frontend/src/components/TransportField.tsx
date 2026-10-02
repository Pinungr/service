import { useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import type { ContactOption, TransportMethod } from '../api/types';
import { ContactSelector } from './ContactSelector';
import { Loading } from './ui';

export interface TransportValue {
  mode: 'BUS' | 'COURIER' | 'IN_HAND';
  service_id: number | null;
  fields: Record<string, string>;
}

/**
 * One transport model, described by the backend (GET /dispatch/methods): Bus uses a saved
 * bus service, Courier stays free text, In hand records the person. Only the chosen
 * method's fields are shown, and switching method clears the fields of the one left.
 */
export function TransportField({ value, onChange }: { value: TransportValue; onChange: (value: TransportValue) => void }) {
  const methods = useQuery({ queryKey: ['transport-methods'], queryFn: () => api.get<{ methods: TransportMethod[] }>('/dispatch/methods'), staleTime: Infinity });
  const couriers = useQuery({ queryKey: ['courier-suggestions'], queryFn: () => api.get<string[]>('/dispatch/courier-suggestions') });
  const prefill = useRef('');
  if (!methods.data) return <Loading />;
  const method = methods.data.methods.find((m) => m.key === value.mode) ?? methods.data.methods[0];
  const setField = (key: string, text: string) => onChange({ ...value, fields: { ...value.fields, [key]: text } });
  const pickService = (id: number | null, option: ContactOption | null) => {
    const usual = String(option?.snapshot?.vehicle_number ?? '');
    const current = value.fields.bus_number ?? '';
    // The usual bus is offered; the actual bus on the day is what gets recorded.
    const fields = usual && (!current || current === prefill.current) ? { ...value.fields, bus_number: usual } : value.fields;
    if (usual) prefill.current = usual;
    onChange({ ...value, service_id: id, fields });
  };

  return (
    <fieldset className="stack" style={{ border: 0, padding: 0, margin: 0 }}>
      <legend className="label required" style={{ fontWeight: 600, marginBottom: 6 }}>Transport method</legend>
      <div className="row" role="radiogroup">
        {methods.data.methods.map((m) => (
          <label key={m.key} className="check">
            <input type="radio" name="transport-method" checked={value.mode === m.key}
                   onChange={() => onChange({ mode: m.key, service_id: null, fields: {} })} />
            {m.label}
          </label>
        ))}
      </div>
      {method.uses_bus_service && (
        <div className="field">
          <span className="label required">Bus / transport service</span>
          <ContactSelector kind="transporter" value={value.service_id} onChange={pickService} />
        </div>
      )}
      <div className="form-grid">
        {method.fields.map((f) => (
          <label key={f.key} className="field">
            <span className={'label' + (f.required ? ' required' : '')}>{f.label}</span>
            <input type={f.type === 'date' ? 'date' : f.type === 'time' ? 'time' : 'text'} value={value.fields[f.key] ?? ''}
                   list={f.key === 'courier_name' ? 'courier-suggestions' : undefined}
                   placeholder={f.key === 'courier_name' ? 'Type any courier company' : undefined}
                   onChange={(e) => setField(f.key, e.target.value)} />
          </label>
        ))}
      </div>
      <datalist id="courier-suggestions">{(couriers.data ?? []).map((name) => <option key={name} value={name} />)}</datalist>
    </fieldset>
  );
}
