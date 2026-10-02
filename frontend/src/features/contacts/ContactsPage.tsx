import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, ApiError, DuplicateMatch, qs } from '../../api/client';
import type { ContactDetail, ContactSummary } from '../../api/types';
import { PageTitle } from '../../app/Layout';
import { useCan } from '../../app/session';
import { KIND_LABELS, ContactKind } from '../../components/ContactSelector';
import { DataTable, ErrorBox, Loading, Modal, Panel, Tabs } from '../../components/ui';
import { formatPaise } from '../../shared/money';

type Section = 'partners' | 'suppliers' | 'transport' | 'setup';
const SETUP: [string, string][] = [['technician', 'Technicians'], ['service', 'Services'], ['category', 'Categories'], ['brand', 'Brands'],
  ['model', 'Models'], ['accessory', 'Accessories'], ['payment_method', 'Payment methods']];

export function ContactsPage() {
  const [section, setSection] = useState<Section>('partners');
  const [partner, setPartner] = useState<ContactKind>('vendor');
  const [setup, setSetup] = useState('technician');
  return (
    <div className="stack">
      <PageTitle title="Contacts & Services" subtitle="Configure partners, suppliers and bus services once. During a repair staff only select them." />
      <Tabs tabs={[{ key: 'partners', label: 'Repair Partners' }, { key: 'suppliers', label: 'Suppliers' }, { key: 'transport', label: 'Transport' }, { key: 'setup', label: 'Shop Setup' }]}
            value={section} onChange={setSection} />
      {section === 'partners' && <>
        <Tabs tabs={[{ key: 'vendor', label: 'Third-Party Repairers' }, { key: 'centre', label: 'Authorized Service Centres' }]} value={partner} onChange={(k) => setPartner(k as ContactKind)} />
        <ContactList key={partner} kind={partner} />
      </>}
      {section === 'suppliers' && <ContactList kind="supplier" />}
      {section === 'transport' && <ContactList kind="transporter" />}
      {section === 'setup' && <>
        <Tabs tabs={SETUP.map(([key, label]) => ({ key, label }))} value={setup} onChange={setSetup} />
        <SetupList key={setup} kind={setup} />
      </>}
    </div>
  );
}

function ContactList({ kind }: { kind: ContactKind }) {
  const can = useCan();
  const client = useQueryClient();
  const [text, setText] = useState('');
  const [search, setSearch] = useState('');
  const [inactive, setInactive] = useState(false);
  const [selected, setSelected] = useState<number | null>(null);
  const [editing, setEditing] = useState<ContactDetail | 'new' | null>(null);
  useEffect(() => { const t = setTimeout(() => setSearch(text.trim()), 200); return () => clearTimeout(t); }, [text]);
  const rows = useQuery({ queryKey: ['contacts', kind, search, inactive], queryFn: () => api.get<ContactSummary[]>('/contacts' + qs({ kind, search, include_inactive: inactive })) });
  const detail = useQuery({ queryKey: ['contact', selected], queryFn: () => api.get<ContactDetail>('/contacts/' + selected), enabled: Boolean(selected) });
  const toggle = useMutation({
    mutationFn: (c: ContactDetail) => api.post(`/contacts/${c.id}/${c.active ? 'deactivate' : 'activate'}`),
    onSuccess: () => { client.invalidateQueries({ queryKey: ['contacts'] }); client.invalidateQueries({ queryKey: ['contact'] }); client.invalidateQueries({ queryKey: ['contact-options'] }); },
  });
  const transport = kind === 'transporter';
  const d = detail.data;
  return (
    <div className="stack">
      <div className="row">
        <input className="grow" style={{ maxWidth: 520 }} placeholder="Search by name, mobile, person, place or work…" value={text} onChange={(e) => setText(e.target.value)} />
        <label className="check"><input type="checkbox" checked={inactive} onChange={(e) => setInactive(e.target.checked)} />Show inactive</label>
        {can('directories') && <button className="primary" onClick={() => setEditing('new')}>+ Add {KIND_LABELS[kind]}</button>}
      </div>
      <DataTable rows={rows.data} onOpen={(r) => setSelected(r.id)} selected={selected}
                 empty={`No ${KIND_LABELS[kind].toLowerCase()}s yet. Add one here, or with "+ Add new" while choosing one during a repair.`}
                 columns={transport ? [
                   { key: 'name', label: 'Name' }, { key: 'works_on', label: 'Route' }, { key: 'pickup_point', label: 'Pickup' }, { key: 'drop_point', label: 'Drop' },
                   { key: 'contact_person', label: 'Contact' }, { key: 'mobile', label: 'Mobile' }, { key: 'vehicle_number', label: 'Usual bus' }, { key: 'status', label: 'Status' }]
                   : [{ key: 'name', label: 'Name' }, { key: 'mobile', label: 'Mobile' }, { key: 'contact_person', label: 'Contact person' },
                      { key: 'location', label: 'Location' }, { key: 'works_on', label: 'Works on' }, { key: 'status', label: 'Status' }]} />
      {d && (
        <Panel title={d.name} actions={can('directories') && <>
          <button onClick={() => setEditing(d)}>Edit</button>
          <button onClick={() => toggle.mutate(d)}>{d.active ? 'Deactivate' : 'Activate'}</button>
        </>}>
          <div className="summary-card">{d.summary}</div>
          <div className="small muted" style={{ marginTop: 8 }}>
            {transport ? `Dispatches: ${d.activity.dispatches ?? 0}${can('financial_reports') ? ' · Transport charges: ' + formatPaise(Number(d.activity.transport_total ?? 0)) : ''}`
              : kind === 'supplier' ? '' : `Repairs: ${d.activity.jobs ?? 0} · Open: ${d.activity.open ?? 0} · Completed: ${d.activity.completed ?? 0} · Unable / returned unrepaired: ${d.activity.unable ?? 0}`
                + (d.activity.turnaround_days !== null && d.activity.turnaround_days !== undefined ? ` · Average turnaround: ${d.activity.turnaround_days} days` : '')
                + (kind === 'centre' ? ` · Warranty jobs: ${d.activity.warranty_jobs ?? 0}` : '')}
          </div>
          {d.notes && <div className="info-box" style={{ marginTop: 8 }}>{d.notes}</div>}
          {!d.active && <div className="notice" style={{ marginTop: 8 }}>Inactive: kept for history, not offered for new repairs.</div>}
          <ErrorBox error={toggle.error} />
        </Panel>
      )}
      {editing && <ContactEditor kind={kind} contact={editing === 'new' ? null : editing} onClose={() => setEditing(null)}
                                 onSaved={(id) => { setEditing(null); setSelected(id); client.invalidateQueries({ queryKey: ['contacts'] }); client.invalidateQueries({ queryKey: ['contact'] }); client.invalidateQueries({ queryKey: ['contact-options'] }); }} />}
    </div>
  );
}

function ContactEditor({ kind, contact, onClose, onSaved }: { kind: ContactKind; contact: ContactDetail | null; onClose: () => void; onSaved: (id: number) => void }) {
  const transport = kind === 'transporter';
  const partner = kind === 'vendor' || kind === 'centre';
  const [v, setV] = useState<Record<string, any>>(() => ({
    name: contact?.name ?? '', mobile: contact?.mobile ?? '', alternate: contact?.alternate ?? '', contact_person: contact?.contact_person ?? '',
    email: contact?.email ?? '', address_line1: contact?.address_line1 ?? '', address_line2: contact?.address_line2 ?? '', city: contact?.city ?? '',
    district: contact?.district ?? '', state: contact?.state ?? '', pincode: contact?.pincode ?? '', specialization: contact?.specialization ?? '',
    notes: contact?.notes ?? '', warranty_service: contact?.warranty_service ?? false, pickup: contact?.pickup ?? false, turnaround_days: contact?.turnaround_days ?? 0,
    route_from: contact?.route_from ?? '', route_to: contact?.route_to ?? '', pickup_point: contact?.pickup_point ?? '', drop_point: contact?.drop_point ?? '',
    vehicle_number: contact?.vehicle_number ?? '', brands: (contact?.brands ?? []).join(', '), supports: contact?.supports ?? [], active: contact?.active ?? true,
  }));
  const [dupes, setDupes] = useState<DuplicateMatch[] | null>(null);
  const categories = useQuery({ queryKey: ['setup', 'category'], queryFn: () => api.get<{ id: number; name: string; active: number }[]>('/setup/category'), enabled: partner });
  const services = useQuery({ queryKey: ['setup', 'service'], queryFn: () => api.get<{ id: number; name: string; active: number }[]>('/setup/service'), enabled: partner });
  const brandIds = useQuery({ queryKey: ['setup', 'brand'], queryFn: () => api.get<{ id: number; name: string }[]>('/setup/brand'), enabled: partner });
  const body = () => {
    const keep = ['name', 'mobile', 'alternate', 'contact_person', 'notes', 'active',
      ...(transport ? ['route_from', 'route_to', 'pickup_point', 'drop_point', 'vehicle_number']
                    : ['email', 'address_line1', 'address_line2', 'city', 'district', 'state', 'pincode', 'specialization']),
      ...(partner ? ['brands'] : []), ...(kind === 'centre' ? ['warranty_service', 'pickup', 'turnaround_days'] : [])];
    const out: Record<string, any> = Object.fromEntries(keep.map((k) => [k, v[k]]));
    if (partner) out.supports = (v.supports as number[]).filter((id) => !(brandIds.data ?? []).some((b) => b.id === id));
    if (kind === 'centre') out.turnaround_days = Number(v.turnaround_days || 0);
    return out;
  };
  const save = useMutation({
    mutationFn: (allowDuplicate: boolean) => contact ? api.patch<ContactDetail>('/contacts/' + contact.id, body())
                                                     : api.post<ContactDetail>('/contacts', { ...body(), kind, allow_duplicate: allowDuplicate }),
    onSuccess: (c) => onSaved(c.id),
    onError: (e) => { if (e instanceof ApiError && e.code === 'DUPLICATE_CONTACT') setDupes(e.body.matches ?? []); },
  });
  const input = (key: string, label: string, required = false) => (
    <label className="field"><span className={'label' + (required ? ' required' : '')}>{label}</span><input value={v[key]} onChange={(e) => setV({ ...v, [key]: e.target.value })} /></label>
  );
  const toggleSupport = (id: number, on: boolean) => setV({ ...v, supports: on ? [...v.supports, id] : v.supports.filter((x: number) => x !== id) });
  const realError = save.error instanceof ApiError && save.error.code === 'DUPLICATE_CONTACT' ? null : save.error;
  if (!categories.data && partner) return <Modal title="Loading" onClose={onClose}><Loading /></Modal>;
  return (
    <Modal title={(contact ? 'Edit ' : 'Add ') + KIND_LABELS[kind]} onClose={onClose} wide>
      <p className="muted">Only name and mobile are required. Everything here is shown to staff when they select this contact.</p>
      <div className="form">
        <div className="form-grid">
          {input('name', 'Name', true)}{input('mobile', 'Mobile', true)}{input('alternate', 'Alternate mobile')}{input('contact_person', 'Contact person')}
          {!transport && input('email', 'Email')}
        </div>
        {transport ? (
          <><h3>Route</h3><div className="form-grid">{input('route_from', 'From')}{input('route_to', 'To')}{input('pickup_point', 'Pickup point')}{input('drop_point', 'Drop point')}{input('vehicle_number', 'Usual bus number')}</div></>
        ) : (
          <><h3>Address</h3><div className="form-grid">{input('address_line1', 'Address line 1')}{input('address_line2', 'Address line 2')}{input('city', 'City')}{input('district', 'District')}{input('state', 'State')}{input('pincode', 'PIN code')}</div>
            <h3>Work</h3><div className="form-grid">{input('specialization', kind === 'supplier' ? 'What they supply' : 'Specialization')}{partner && input('brands', 'Brands (comma separated)')}</div></>
        )}
        {partner && (
          <div className="grid2">
            {[['Product categories', categories.data ?? []], ['Repairs / services', services.data ?? []]].map(([title, list]) => (
              <fieldset key={title as string} className="panel tight"><legend className="small muted">{title as string}</legend>
                {(list as { id: number; name: string; active: number }[]).filter((x) => x.active).map((x) => (
                  <label key={x.id} className="check" style={{ fontWeight: 400 }}><input type="checkbox" checked={v.supports.includes(x.id)} onChange={(e) => toggleSupport(x.id, e.target.checked)} />{x.name}</label>
                ))}
              </fieldset>
            ))}
          </div>
        )}
        {kind === 'centre' && (
          <div className="row">
            <label className="check"><input type="checkbox" checked={v.warranty_service} onChange={(e) => setV({ ...v, warranty_service: e.target.checked })} />Accepts warranty jobs</label>
            <label className="check"><input type="checkbox" checked={v.pickup} onChange={(e) => setV({ ...v, pickup: e.target.checked })} />Offers pickup</label>
            <label className="field" style={{ maxWidth: 200 }}><span className="label">Usual turnaround (days)</span><input type="number" min={0} value={v.turnaround_days} onChange={(e) => setV({ ...v, turnaround_days: e.target.value })} /></label>
          </div>
        )}
        <label className="field"><span className="label">Notes</span><textarea value={v.notes} onChange={(e) => setV({ ...v, notes: e.target.value })} /></label>
        <label className="check"><input type="checkbox" checked={v.active} onChange={(e) => setV({ ...v, active: e.target.checked })} />Available for new work</label>
        {dupes && (
          <div className="stack">
            <div className="notice">This looks like a contact you already have:</div>
            {dupes.map((m) => <div key={m.id} className="row between panel tight"><div><strong>{m.name}</strong><div className="small muted">{m.secondary} · {m.reasons.join(', ')}</div></div>
              <button onClick={() => onSaved(m.id)}>Use existing</button></div>)}
            {!dupes.some((m) => m.exact) && <div><button onClick={() => save.mutate(true)}>Create anyway</button></div>}
          </div>
        )}
        <ErrorBox error={realError} />
        <div className="row"><button className="primary" disabled={save.isPending} onClick={() => save.mutate(false)}>Save</button><button onClick={onClose}>Cancel</button></div>
      </div>
    </Modal>
  );
}

interface SetupRow { id: number; name: string; contact: string; details: string; active: number; category_id: number | null; category_ids?: number[] }

function SetupList({ kind }: { kind: string }) {
  const can = useCan();
  const client = useQueryClient();
  const rows = useQuery({ queryKey: ['setup', kind], queryFn: () => api.get<SetupRow[]>('/setup/' + kind) });
  const categories = useQuery({ queryKey: ['setup', 'category'], queryFn: () => api.get<SetupRow[]>('/setup/category'), enabled: kind === 'service' || kind === 'accessory' });
  const [editing, setEditing] = useState<SetupRow | 'new' | null>(null);
  const [v, setV] = useState<Record<string, any>>({});
  useEffect(() => {
    if (!editing) return;
    const row = editing === 'new' ? null : editing;
    setV({ name: row?.name ?? '', contact: row?.contact ?? '', details: row?.details ?? '', active: row ? Boolean(row.active) : true,
           category_id: row?.category_id ?? '', category_ids: row?.category_ids ?? [] });
  }, [editing]);
  const save = useMutation({
    mutationFn: () => {
      const payload: Record<string, any> = { name: v.name, contact: v.contact, details: v.details, active: v.active };
      if (kind === 'service') payload.category_ids = v.category_ids;
      if (kind === 'accessory' && v.category_id) payload.category_id = Number(v.category_id);
      return editing === 'new' ? api.post('/setup/' + kind, payload) : api.patch(`/setup/${kind}/${(editing as SetupRow).id}`, payload);
    },
    onSuccess: () => { setEditing(null); client.invalidateQueries({ queryKey: ['setup'] }); },
  });
  return (
    <div className="stack">
      {can('directories') && <div><button className="primary" onClick={() => setEditing('new')}>+ Add</button></div>}
      <DataTable rows={rows.data} onOpen={can('directories') ? setEditing : undefined} columns={[
        { key: 'name', label: 'Name' }, { key: 'contact', label: 'Phone / contact' }, { key: 'details', label: 'Details' },
        { key: 'active', label: 'Active', render: (r) => (r.active ? 'Yes' : 'No') }]} />
      {editing && (
        <Modal title={editing === 'new' ? 'Add' : 'Edit ' + (editing as SetupRow).name} onClose={() => setEditing(null)}>
          <div className="form">
            <label className="field"><span className="label required">Name</span><input value={v.name ?? ''} onChange={(e) => setV({ ...v, name: e.target.value })} /></label>
            <label className="field"><span className="label">Phone / contact</span><input value={v.contact ?? ''} onChange={(e) => setV({ ...v, contact: e.target.value })} /></label>
            <label className="field"><span className="label">Details</span><textarea value={v.details ?? ''} onChange={(e) => setV({ ...v, details: e.target.value })} /></label>
            {kind === 'accessory' && <label className="field"><span className="label">Suggest for category</span>
              <select value={v.category_id ?? ''} onChange={(e) => setV({ ...v, category_id: e.target.value })}><option value="">—</option>
                {(categories.data ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label>}
            {kind === 'service' && <fieldset className="panel tight"><legend className="small muted">Applicable categories (none = general service)</legend>
              {(categories.data ?? []).map((c) => <label key={c.id} className="check" style={{ fontWeight: 400 }}>
                <input type="checkbox" checked={(v.category_ids ?? []).includes(c.id)}
                       onChange={(e) => setV({ ...v, category_ids: e.target.checked ? [...v.category_ids, c.id] : v.category_ids.filter((x: number) => x !== c.id) })} />{c.name}</label>)}
            </fieldset>}
            <label className="check"><input type="checkbox" checked={Boolean(v.active)} onChange={(e) => setV({ ...v, active: e.target.checked })} />Available for new work</label>
            <ErrorBox error={save.error} />
            <div className="row"><button className="primary" disabled={save.isPending} onClick={() => save.mutate()}>Save</button><button onClick={() => setEditing(null)}>Cancel</button></div>
          </div>
        </Modal>
      )}
    </div>
  );
}
