import { KeyboardEvent, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, ApiError, DuplicateMatch, qs } from '../api/client';
import type { ContactOption, ContactOptions } from '../api/types';
import { ErrorBox, Modal } from './ui';

export type ContactKind = 'vendor' | 'centre' | 'supplier' | 'transporter';

export const KIND_LABELS: Record<ContactKind, string> = {
  vendor: 'Third-Party Repairer', centre: 'Authorized Service Centre', supplier: 'Supplier', transporter: 'Bus / Transport Service',
};

/** The few extra details asked for when a contact is created from inside a repair. */
const QUICK_FIELDS: Record<ContactKind, [string, string][]> = {
  vendor: [['specialization', 'Specialization (e.g. Laptop, motherboard, chip-level)']],
  centre: [['brands', 'Brand / OEM (e.g. Samsung)'], ['city', 'City']],
  supplier: [['specialization', 'What they supply']],
  transporter: [['route_from', 'Route from'], ['route_to', 'Route to'], ['vehicle_number', 'Usual bus number']],
};

/**
 * Search and select one active contact. Relevant contacts are listed first because the
 * backend ranked them; nothing is hidden. "+ Add new" creates the contact centrally and
 * selects it without leaving the repair.
 */
export function ContactSelector({ kind, jobId, value, onChange }: {
  kind: ContactKind; jobId?: number | null; value: number | null; onChange: (id: number | null, option: ContactOption | null) => void;
}) {
  const [search, setSearch] = useState('');
  const [open, setOpen] = useState(false);
  const [focus, setFocus] = useState(0);
  const [adding, setAdding] = useState(false);
  const key = ['contact-options', kind, jobId ?? null];
  const options = useQuery({ queryKey: key, queryFn: () => api.get<ContactOptions>('/contacts/options' + qs({ kind, job_id: jobId })) });
  const all = useMemo(() => [...(options.data?.recommended ?? []), ...(options.data?.others ?? [])], [options.data]);
  const selected = all.find((o) => o.id === value) ?? null;
  const term = search.trim().toLowerCase();
  const matches = (o: ContactOption) => !term || (o.name + ' ' + o.secondary + ' ' + o.headline).toLowerCase().includes(term);
  const recommended = (options.data?.recommended ?? []).filter(matches);
  const others = (options.data?.others ?? []).filter(matches);
  const flat = [...recommended, ...others];

  const choose = (option: ContactOption | null) => {
    onChange(option?.id ?? null, option);
    setOpen(false);
    setSearch('');
  };
  const onKey = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'ArrowDown') { setOpen(true); setFocus((f) => Math.min(flat.length - 1, f + 1)); event.preventDefault(); }
    if (event.key === 'ArrowUp') { setFocus((f) => Math.max(0, f - 1)); event.preventDefault(); }
    if (event.key === 'Enter' && open && flat[focus]) { choose(flat[focus]); event.preventDefault(); }
    if (event.key === 'Escape') setOpen(false);
  };
  const label = KIND_LABELS[kind].toLowerCase();

  return (
    <div>
      {selected && !open ? (
        <div>
          <div className="summary-card">{selected.summary}
            {selected.recommended && selected.reasons.length > 0 && <div className="small muted">Recommended: works on {selected.reasons.join(', ')}</div>}
          </div>
          <div className="row" style={{ marginTop: 6 }}>
            <button type="button" onClick={() => setOpen(true)}>Change</button>
          </div>
        </div>
      ) : (
        <div className="row" style={{ alignItems: 'flex-start' }}>
          <div className="grow" style={{ minWidth: 220 }}>
            <input aria-label={'Search ' + label} placeholder={'Search ' + label + ' by name, place or phone…'} value={search}
                   onFocus={() => setOpen(true)} onChange={(e) => { setSearch(e.target.value); setOpen(true); setFocus(0); }} onKeyDown={onKey} />
            {open && (
              <div className="selector-list" role="listbox">
                {options.isLoading && <div className="selector-item muted">Loading…</div>}
                {!options.isLoading && flat.length === 0 && <div className="selector-item muted">No matching {label}. Use + Add new.</div>}
                {recommended.length > 0 && <div className="selector-group">Recommended for this product</div>}
                {recommended.map((o, i) => <Item key={o.id} option={o} focused={focus === i} onPick={choose} />)}
                {recommended.length > 0 && others.length > 0 && <div className="selector-group">Other {label}s</div>}
                {others.map((o, i) => <Item key={o.id} option={o} focused={focus === recommended.length + i} onPick={choose} />)}
              </div>
            )}
          </div>
          <button type="button" onClick={() => setAdding(true)}>+ Add new</button>
          {selected && <button type="button" onClick={() => setOpen(false)}>Keep {selected.name}</button>}
        </div>
      )}
      {adding && <QuickCreate kind={kind} jobId={jobId} initialName={search} onClose={() => setAdding(false)}
                              onSelected={(option) => { setAdding(false); choose(option); }} />}
    </div>
  );
}

function Item({ option, focused, onPick }: { option: ContactOption; focused: boolean; onPick: (o: ContactOption) => void }) {
  return (
    <div role="option" aria-selected={focused} className={'selector-item' + (focused ? ' focused' : '')} onMouseDown={(e) => { e.preventDefault(); onPick(option); }}>
      <div><strong>{option.name}</strong></div>
      {option.secondary && <div className="secondary">{option.secondary}</div>}
    </div>
  );
}

function QuickCreate({ kind, jobId, initialName, onClose, onSelected }: {
  kind: ContactKind; jobId?: number | null; initialName: string; onClose: () => void; onSelected: (option: ContactOption) => void;
}) {
  const client = useQueryClient();
  const [values, setValues] = useState<Record<string, string>>({ name: initialName, mobile: '' });
  const [duplicates, setDuplicates] = useState<DuplicateMatch[] | null>(null);
  const refresh = () => client.invalidateQueries({ queryKey: ['contact-options', kind] });
  const create = useMutation({
    mutationFn: (allowDuplicate: boolean) =>
      api.post<ContactOption>('/contacts/quick-create', { ...values, kind, job_id: jobId ?? null, allow_duplicate: allowDuplicate }),
    onSuccess: async (option) => { await refresh(); client.invalidateQueries({ queryKey: ['contacts'] }); onSelected(option); },
    onError: (error) => {
      if (error instanceof ApiError && error.code === 'DUPLICATE_CONTACT') setDuplicates(error.body.matches ?? []);
    },
  });
  const useExisting = useMutation({
    mutationFn: async (match: DuplicateMatch) => {
      if (!match.active) await api.post(`/contacts/${match.id}/activate`);
      await refresh();
      const options = await api.get<ContactOptions>('/contacts/options' + qs({ kind, job_id: jobId }));
      return [...options.recommended, ...options.others].find((o) => o.id === match.id)!;
    },
    onSuccess: (option) => onSelected(option),
  });
  const set = (key: string) => (e: { target: { value: string } }) => setValues({ ...values, [key]: e.target.value });
  const realError = create.error instanceof ApiError && create.error.code === 'DUPLICATE_CONTACT' ? null : create.error;

  return (
    <Modal title={'Add ' + KIND_LABELS[kind]} onClose={onClose}>
      <p className="muted">Saved once in Contacts &amp; Services and selected for this repair. Complete the address and other details later from Contacts &amp; Services.</p>
      {duplicates ? (
        <div className="stack">
          <div className="notice">This looks like a contact you already have:</div>
          {duplicates.map((m) => (
            <div key={m.id} className="row between panel tight">
              <div><strong>{m.name}</strong>{!m.active && <span className="badge">inactive</span>}
                <div className="small muted">{m.secondary} · {m.reasons.join(', ')}</div></div>
              <button className="primary" onClick={() => useExisting.mutate(m)} disabled={useExisting.isPending}>Use existing</button>
            </div>
          ))}
          <ErrorBox error={useExisting.error || realError} />
          <div className="row">
            {!duplicates.some((m) => m.exact) && <button onClick={() => create.mutate(true)} disabled={create.isPending}>Create anyway</button>}
            <button onClick={() => setDuplicates(null)}>Back</button>
          </div>
        </div>
      ) : (
        <form className="form" onSubmit={(e) => { e.preventDefault(); create.mutate(false); }}>
          <label className="field"><span className="label required">Name</span><input value={values.name} onChange={set('name')} /></label>
          <label className="field"><span className="label required">Mobile</span><input inputMode="tel" value={values.mobile} onChange={set('mobile')} /></label>
          {QUICK_FIELDS[kind].map(([key, label]) => (
            <label key={key} className="field"><span className="label">{label}</span><input value={values[key] ?? ''} onChange={set(key)} /></label>
          ))}
          <ErrorBox error={realError} />
          <div className="row">
            <button className="primary" disabled={create.isPending || !values.name.trim() || !values.mobile.trim()}>Save &amp; Select</button>
            <button type="button" onClick={onClose}>Cancel</button>
          </div>
        </form>
      )}
    </Modal>
  );
}
