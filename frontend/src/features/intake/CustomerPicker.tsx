import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, ApiError, qs } from '../../api/client';
import type { CustomerSummary, Page } from '../../api/types';
import { PhotoCapture, photoForm } from '../../components/PhotoCapture';
import { ErrorBox, Modal } from '../../components/ui';

export interface CustomerFormValues {
  name: string; phone_number: string; alternate: string; email: string; whatsapp_consent: boolean; email_consent: boolean;
  address_line1: string; address_line2: string; district: string; state: string; pincode: string;
}

const EMPTY: CustomerFormValues = { name: '', phone_number: '', alternate: '', email: '', whatsapp_consent: false, email_consent: false,
  address_line1: '', address_line2: '', district: '', state: '', pincode: '' };

/** Find a customer by name or phone, or register one without leaving the counter. */
export function CustomerPicker({ onPick }: { onPick: (customer: CustomerSummary) => void }) {
  const [text, setText] = useState('');
  const [term, setTerm] = useState('');
  const [creating, setCreating] = useState(false);
  useEffect(() => { const t = setTimeout(() => setTerm(text.trim()), 200); return () => clearTimeout(t); }, [text]);
  const results = useQuery({ queryKey: ['customers', term, 0], queryFn: () => api.get<Page<CustomerSummary>>('/customers' + qs({ search: term })), enabled: term.length > 1 });
  const digits = text.replace(/\D/g, '');
  return (
    <div className="stack">
      <div className="row">
        <input className="grow" autoFocus placeholder="Find customer by name or phone…" value={text} onChange={(e) => setText(e.target.value)} aria-label="Find customer" />
        <button onClick={() => setCreating(true)}>+ New customer</button>
      </div>
      {term.length > 1 && (
        <div className="selector-list">
          {results.data?.items.length === 0 && <div className="selector-item muted">No customer found. Use + New customer.</div>}
          {results.data?.items.map((c) => (
            <div key={c.id} className="selector-item" onClick={() => onPick(c)}>
              <strong>{c.name}</strong><div className="secondary">{c.phone} · {c.address || 'No address recorded'}</div>
            </div>
          ))}
        </div>
      )}
      {creating && <CustomerEditor initial={{ ...EMPTY, ...(digits.length >= 6 ? { phone_number: text.trim() } : { name: text.trim() }) }}
                                   onClose={() => setCreating(false)} onSaved={(c) => { setCreating(false); onPick(c); }} />}
    </div>
  );
}

export function CustomerEditor({ initial, customerId, onClose, onSaved }: {
  initial: CustomerFormValues; customerId?: number; onClose: () => void; onSaved: (customer: CustomerSummary & { current_photo_id?: number | null }) => void;
}) {
  const client = useQueryClient();
  const [values, setValues] = useState(initial);
  const [shared, setShared] = useState<CustomerSummary[] | null>(null);
  const [photoFor, setPhotoFor] = useState<CustomerSummary | null>(null);
  const save = useMutation({
    mutationFn: (confirm: boolean) => {
      const body = { ...values, complete: Boolean(values.address_line1), confirm_shared_phone: confirm };
      return customerId ? api.patch<CustomerSummary & { current_photo_id: number | null }>(`/customers/${customerId}`, body)
                        : api.post<CustomerSummary & { current_photo_id: number | null }>('/customers', body);
    },
    onSuccess: (customer) => {
      client.invalidateQueries({ queryKey: ['customers'] });
      if (!customerId && !customer.current_photo_id) setPhotoFor(customer);
      else onSaved(customer);
    },
    onError: async (error) => {
      if (error instanceof ApiError && error.code === 'DUPLICATE_PHONE') {
        setShared(await api.get<CustomerSummary[]>('/customers/phone-matches' + qs({ phone: values.phone_number, exclude_id: customerId })));
      }
    },
  });
  const photo = useMutation({
    mutationFn: ({ blob, name }: { blob: Blob; name: string }) => api.upload(`/customers/${photoFor!.id}/photos`, photoForm(blob, name, { role: 'owner' })),
    onSuccess: async () => { const c = await api.get<{ customer: CustomerSummary & { current_photo_id: number | null } }>(`/customers/${photoFor!.id}`); onSaved(c.customer); },
  });
  const set = (key: keyof CustomerFormValues) => (e: { target: { value: string; checked?: boolean; type?: string } }) =>
    setValues({ ...values, [key]: e.target.type === 'checkbox' ? Boolean(e.target.checked) : e.target.value });
  if (photoFor) {
    return <PhotoCapture title={`Customer photo · ${photoFor.name}`} busy={photo.isPending} error={photo.error}
                         onPhoto={(blob, name) => photo.mutate({ blob, name })} onClose={() => onSaved(photoFor)} />;
  }
  const realError = save.error instanceof ApiError && save.error.code === 'DUPLICATE_PHONE' ? null : save.error;
  return (
    <Modal title={customerId ? 'Edit customer' : 'Register customer'} onClose={onClose} wide>
      <form className="form" onSubmit={(e) => { e.preventDefault(); save.mutate(false); }}>
        <div className="form-grid">
          <label className="field"><span className="label required">Full name</span><input value={values.name} onChange={set('name')} /></label>
          <label className="field"><span className="label required">Phone / WhatsApp number</span><input inputMode="tel" value={values.phone_number} onChange={set('phone_number')} /></label>
          <label className="field"><span className="label">Alternate phone</span><input inputMode="tel" value={values.alternate} onChange={set('alternate')} /></label>
          <label className="field"><span className="label">Email</span><input type="email" value={values.email} onChange={set('email')} /></label>
          <label className="check"><input type="checkbox" checked={values.whatsapp_consent} onChange={set('whatsapp_consent')} />Agrees to WhatsApp updates</label>
          <label className="check"><input type="checkbox" checked={values.email_consent} onChange={set('email_consent')} />Agrees to email updates</label>
          <label className="field"><span className="label">Address line 1</span><input value={values.address_line1} onChange={set('address_line1')} /></label>
          <label className="field"><span className="label">Address line 2</span><input value={values.address_line2} onChange={set('address_line2')} /></label>
          <label className="field"><span className="label">District</span><input value={values.district} onChange={set('district')} /></label>
          <label className="field"><span className="label">State</span><input value={values.state} onChange={set('state')} /></label>
          <label className="field"><span className="label">PIN code</span><input inputMode="numeric" value={values.pincode} onChange={set('pincode')} /></label>
        </div>
        <p className="small muted">The postal address can be completed later; a quick counter registration needs only name and phone.</p>
        {shared && (
          <div className="stack">
            <div className="notice">An existing customer uses this phone number. Use their record, or confirm that this is a different person sharing the number.</div>
            {shared.map((c) => (
              <div key={c.id} className="row between panel tight">
                <div><strong>{c.name}</strong><div className="small muted">{c.phone} · {c.address || 'No address'}</div></div>
                <button type="button" className="primary" onClick={() => onSaved(c)}>Use this customer</button>
              </div>
            ))}
            <div><button type="button" onClick={() => save.mutate(true)}>This is a different person — save</button></div>
          </div>
        )}
        <ErrorBox error={realError} />
        <div className="row"><button className="primary" disabled={save.isPending}>Save customer</button><button type="button" onClick={onClose}>Cancel</button></div>
      </form>
    </Modal>
  );
}
