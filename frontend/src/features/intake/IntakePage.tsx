import { useEffect, useRef, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { api, operationId } from '../../api/client';
import type { CustomerSummary, StoredFile } from '../../api/types';
import { PageTitle } from '../../app/Layout';
import { PhotoCapture, photoForm } from '../../components/PhotoCapture';
import { DataTable, ErrorBox, Loading, Panel } from '../../components/ui';
import { formatDateTime, shopToday } from '../../shared/dates';
import { formatPaise, parseRupees } from '../../shared/money';
import { CustomerPicker } from './CustomerPicker';

interface Reference { categories: { id: number; name: string }[]; conditions: string[]; policies: { value: string; label: string }[]; default_policy: string }
interface Accessory { checked: boolean; quantity: number; serial: string; condition: string; notes: string; photo_id: number | null }
interface Product {
  device_id: number | null; sale_id: number | null; category_id: number | null; service_id: number | null;
  device: string; brand: string; model: string; serial: string; origin: string; complaint: string; damage: string; customer_requirement: string;
  submitter: string; relationship: string; repair_due: string; collection_due: string; policy: string; assessment_consent: boolean;
  transport_agreed: string; assessment_agreed: string; initial_estimate: string; deposit: string; advance: string;
  accessories: Record<string, Accessory>; product_photos: number[];
  warranty_status: string; warranty_expiry: string; warranty_provider: string; warranty_notes: string;
}
interface Customer extends CustomerSummary { current_photo_id?: number | null }
interface Overview { customer: Customer; devices: { id: number; name: string; brand: string; model: string; serial: string; category_id: number | null }[] }
interface Sale { id: number; device: string; serial: string; warranty_end: string | null; collected: number }
interface Received { jobs: { id: number; number: string; device: string }[]; visit: { number: string } | null; documents: (StoredFile & { job_id: number })[]; notes: string[] }

const AMOUNTS = ['transport_agreed', 'assessment_agreed', 'initial_estimate', 'deposit', 'advance'] as const;

function blankProduct(policy: string): Product {
  return { device_id: null, sale_id: null, category_id: null, service_id: null, device: '', brand: '', model: '', serial: '', origin: 'elsewhere',
    complaint: '', damage: '', customer_requirement: '', submitter: '', relationship: '', repair_due: '', collection_due: '', policy,
    assessment_consent: false, transport_agreed: '0', assessment_agreed: '0', initial_estimate: '0', deposit: '0', advance: '0',
    accessories: {}, product_photos: [], warranty_status: 'UNKNOWN', warranty_expiry: '', warranty_provider: '', warranty_notes: '' };
}

/** Product as the visit API expects it: amounts as whole paise, only ticked accessories. */
function toPayload(p: Product, customer: Customer) {
  const amounts: Record<string, number> = {};
  for (const key of AMOUNTS) {
    const value = parseRupees(p[key]);
    if (value === null || value < 0) throw new Error(`Enter ${key.replace(/_/g, ' ')} as an amount, for example 500 or 500.50.`);
    amounts[key] = value;
  }
  return {
    customer_id: customer.id, photo_id: customer.current_photo_id, device_id: p.device_id, sale_id: p.sale_id, category_id: p.category_id,
    service_id: p.service_id, device: p.device.trim(), brand: p.brand.trim() || null, model: p.model.trim() || null, serial: p.serial.trim(),
    origin: p.origin, complaint: p.complaint.trim(), damage: p.damage.trim(), customer_requirement: p.customer_requirement.trim(),
    submitter: p.submitter.trim(), relationship: p.relationship.trim(), repair_due: p.repair_due || null, collection_due: p.collection_due || null,
    policy: p.policy || null, assessment_consent: p.assessment_consent, ...amounts, product_photos: p.product_photos,
    accessories: Object.entries(p.accessories).filter(([, a]) => a.checked).map(([description, a]) => ({
      description, quantity: a.quantity, serial: a.serial, condition: a.condition, notes: a.notes, photo_id: a.photo_id })),
    ...(p.sale_id ? {} : { warranty_status: p.warranty_status, warranty_expiry: p.warranty_status === 'VALID' ? p.warranty_expiry || null : null,
                           warranty_provider: p.warranty_status === 'VALID' ? p.warranty_provider : '', warranty_notes: p.warranty_status === 'VALID' ? p.warranty_notes : '' }),
  };
}

export function IntakePage() {
  const reference = useQuery({ queryKey: ['intake-reference'], queryFn: () => api.get<Reference>('/intake/reference') });
  const drafts = useQuery({ queryKey: ['intake-drafts'], queryFn: () => api.get<{ id: string; customer: string | null; updated: string }[]>('/intake/drafts') });
  const [draftId, setDraftId] = useState(() => operationId());
  const [customer, setCustomer] = useState<Customer | null>(null);
  const [product, setProduct] = useState<Product | null>(null);
  const [basket, setBasket] = useState<Product[]>([]);
  const [result, setResult] = useState<Received | null>(null);
  const [problem, setProblem] = useState('');
  const visitOp = useRef(operationId());
  const policy = reference.data?.default_policy ?? 'NO_CUSTOMER_CHARGE';

  useEffect(() => { if (reference.data && !product) setProduct(blankProduct(policy)); }, [reference.data, product, policy]);
  // Durable draft: the counter can be interrupted and resume later from any screen.
  useEffect(() => {
    if (!customer || result) return;
    const t = setTimeout(() => { api.put(`/intake/drafts/${draftId}`, { payload: { customer_id: customer.id, customer, current: product, visit_products: basket } }).catch(() => undefined); }, 1500);
    return () => clearTimeout(t);
  }, [customer, product, basket, draftId, result]);

  const receive = useMutation({
    mutationFn: () => {
      if (!customer) throw new Error('Select or register the customer first.');
      const products = [...basket, ...(product && (product.device || product.complaint) ? [product] : [])];
      return api.post<Received>('/intake/visits', { products: products.map((p) => toPayload(p, customer)), operation_id: visitOp.current, draft_id: draftId });
    },
    onSuccess: (r) => setResult(r),
  });
  const resume = async (id: string) => {
    const d = await api.get<{ payload: { customer?: Customer; current?: Product; visit_products?: Product[] } }>('/intake/drafts/' + id);
    setDraftId(id);
    setCustomer(d.payload.customer ?? null);
    setProduct(d.payload.current ?? blankProduct(policy));
    setBasket(d.payload.visit_products ?? []);
  };
  const addToVisit = () => {
    if (!product || !customer) return;
    try { toPayload(product, customer); } catch (e) { setProblem((e as Error).message); return; }
    if (!product.device.trim() || !product.complaint.trim()) { setProblem('Enter the device description and reported fault for this product.'); return; }
    if (product.device_id && basket.some((b) => b.device_id === product.device_id)) { setProblem('This physical device is already in the visit list.'); return; }
    setProblem('');
    setBasket([...basket, product]);
    setProduct(blankProduct(policy));
  };
  const restart = () => { setResult(null); setCustomer(null); setBasket([]); setProduct(blankProduct(policy)); setDraftId(operationId()); visitOp.current = operationId(); drafts.refetch(); };

  if (!reference.data || !product) return <Loading />;
  if (result) return <IntakeResult result={result} onAnother={restart} />;
  return (
    <div className="stack">
      <PageTitle title="New Repair Intake" subtitle="Customer and photo · product and fault · accessories and condition · review" />
      {!customer && drafts.data && drafts.data.length > 0 && (
        <Panel title="Resume a saved intake">
          <div className="row">{drafts.data.slice(0, 6).map((d) => <button key={d.id} onClick={() => resume(d.id)}>{d.customer ?? 'No customer yet'} · {formatDateTime(d.updated)}</button>)}</div>
        </Panel>
      )}
      <Panel title="1 · Customer">
        {customer ? <SelectedCustomer customer={customer} onChange={() => { setCustomer(null); setBasket([]); }} onPhoto={(c) => setCustomer(c)} locked={basket.length > 0} />
                  : <CustomerPicker onPick={async (c) => { const o = await api.get<Overview>(`/customers/${c.id}`); setCustomer(o.customer); }} />}
      </Panel>
      {customer && <ProductEditor customer={customer} reference={reference.data} product={product} onChange={setProduct} />}
      {customer && (
        <Panel title={`Visit · ${basket.length} product(s) listed`}>
          {basket.length > 0 && <DataTable rows={basket.map((b, i) => ({ ...b, id: i }))} columns={[
            { key: 'device', label: 'Product' }, { key: 'complaint', label: 'Fault' },
            { key: 'initial_estimate', label: 'Estimate', render: (b) => formatPaise(parseRupees(b.initial_estimate) ?? 0) },
            { key: 'remove', label: '', render: (b) => <div className="row">
              <button onClick={() => { setProduct(b); setBasket(basket.filter((_, i) => i !== b.id)); }}>Edit</button>
              <button onClick={() => setBasket(basket.filter((_, i) => i !== b.id))}>Remove</button></div> }]} />}
          <p className="small muted">Each device gets its own repair job. Customer details and photo are shared by the whole visit.</p>
          {problem && <div className="error">{problem}</div>}
          <ErrorBox error={receive.error} />
          <div className="row">
            <button onClick={addToVisit}>+ Add this product and enter another</button>
            <button className="primary" disabled={receive.isPending} onClick={() => receive.mutate()}>
              {receive.isPending ? 'Receiving…' : `Receive ${basket.length + (product.device || product.complaint ? 1 : 0)} product(s)`}</button>
          </div>
        </Panel>
      )}
    </div>
  );
}

function SelectedCustomer({ customer, onChange, onPhoto, locked }: { customer: Customer; onChange: () => void; onPhoto: (c: Customer) => void; locked: boolean }) {
  const [capturing, setCapturing] = useState(false);
  const photo = useMutation({
    mutationFn: async ({ blob, name }: { blob: Blob; name: string }) => {
      await api.upload(`/customers/${customer.id}/photos`, photoForm(blob, name, { role: 'owner' }));
      return (await api.get<Overview>(`/customers/${customer.id}`)).customer;
    },
    onSuccess: (c) => { setCapturing(false); onPhoto(c); },
  });
  return (
    <div className="row">
      {customer.current_photo_id ? <img className="photo" src={`/api/files/${customer.current_photo_id}`} alt={'Photo of ' + customer.name} />
                                 : <div className="notice">A customer photo is required before the products can be received.</div>}
      <div className="grow"><strong>{customer.name}</strong><div className="muted">{customer.phone}</div></div>
      <button onClick={() => setCapturing(true)}>{customer.current_photo_id ? 'Retake photo' : 'Capture photo'}</button>
      {!locked && <button onClick={onChange}>Change customer</button>}
      {capturing && <PhotoCapture title={'Customer photo · ' + customer.name} busy={photo.isPending} error={photo.error}
                                  onPhoto={(blob, name) => photo.mutate({ blob, name })} onClose={() => setCapturing(false)} />}
    </div>
  );
}

function ProductEditor({ customer, reference, product: p, onChange }: { customer: Customer; reference: Reference; product: Product; onChange: (p: Product) => void }) {
  const overview = useQuery({ queryKey: ['customer', customer.id], queryFn: () => api.get<Overview>(`/customers/${customer.id}`) });
  const sales = useQuery({ queryKey: ['customer-sales', customer.id], queryFn: () => api.get<Sale[]>(`/customers/${customer.id}/sales`).catch(() => [] as Sale[]) });
  const services = useQuery({ queryKey: ['services', p.category_id], queryFn: () => api.get<{ id: number; name: string; general: boolean }[]>(`/intake/categories/${p.category_id}/services`), enabled: Boolean(p.category_id) });
  const accessories = useQuery({ queryKey: ['accessories', p.category_id], queryFn: () => api.get<{ id: number; name: string }[]>(`/intake/categories/${p.category_id}/accessories`), enabled: Boolean(p.category_id) });
  const [photoTarget, setPhotoTarget] = useState<string | null>(null);
  const set = <K extends keyof Product>(key: K, value: Product[K]) => onChange({ ...p, [key]: value });
  const text = (key: keyof Product) => (e: { target: { value: string } }) => set(key, e.target.value as never);
  const accessory = (name: string): Accessory => p.accessories[name] ?? { checked: false, quantity: 1, serial: '', condition: 'Not Tested', notes: '', photo_id: null };
  const setAccessory = (name: string, patch: Partial<Accessory>) => set('accessories', { ...p.accessories, [name]: { ...accessory(name), ...patch } });
  const capture = useMutation({
    mutationFn: ({ blob, name }: { blob: Blob; name: string }) => {
      const role = photoTarget === '__product__' ? 'product' : 'accessory';
      const description = photoTarget === '__product__' ? p.device : photoTarget!;
      if (!description.trim()) throw new Error(role === 'product' ? 'Enter the product description before photographing it.' : 'Describe the accessory first.');
      return api.upload<{ id: number }>('/intake/photos', photoForm(blob, name, { customer_id: customer.id, role, description }));
    },
    onSuccess: ({ id }) => {
      if (photoTarget === '__product__') set('product_photos', [...p.product_photos, id]);
      else setAccessory(photoTarget!, { photo_id: id });
      setPhotoTarget(null);
    },
  });
  const pickDevice = (id: number | null) => {
    const d = overview.data?.devices.find((x) => x.id === id);
    onChange({ ...p, device_id: id, device: d?.name ?? p.device, brand: d?.brand ?? p.brand, model: d?.model ?? p.model, serial: d?.serial ?? p.serial,
               category_id: d?.category_id ?? p.category_id });
  };
  const sale = sales.data?.find((s) => s.id === p.sale_id);
  return (
    <>
      <Panel title="2 · Product & reported fault">
        <div className="form-grid">
          <label className="field"><span className="label">Physical device</span>
            <select value={p.device_id ?? ''} onChange={(e) => pickDevice(e.target.value ? Number(e.target.value) : null)}>
              <option value="">New physical device</option>
              {(overview.data?.devices ?? []).map((d) => <option key={d.id} value={d.id}>{d.name} · DEV-{String(d.id).padStart(6, '0')}</option>)}
            </select></label>
          <label className="field"><span className="label">Bought from this shop (sale)</span>
            <select value={p.sale_id ?? ''} onChange={(e) => set('sale_id', e.target.value ? Number(e.target.value) : null)}>
              <option value="">Not linked</option>
              {(sales.data ?? []).map((s) => <option key={s.id} value={s.id}>{s.device}{s.serial ? ' · ' + s.serial : ''}</option>)}
            </select></label>
          <label className="field"><span className="label">Product category</span>
            <select value={p.category_id ?? ''} onChange={(e) => onChange({ ...p, category_id: e.target.value ? Number(e.target.value) : null, service_id: null, accessories: {} })}>
              <option value="">Choose…</option>
              {reference.categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select></label>
          <label className="field"><span className="label">Repair / service</span>
            <select value={p.service_id ?? ''} disabled={!p.category_id} onChange={(e) => set('service_id', e.target.value ? Number(e.target.value) : null)}>
              <option value="">{p.category_id ? 'Choose…' : 'Choose a product category first…'}</option>
              {(services.data ?? []).map((s) => <option key={s.id} value={s.id}>{s.name}{s.general ? ' (all categories)' : ''}</option>)}
            </select></label>
          <label className="field"><span className="label required">Product description</span><input value={p.device} onChange={text('device')} placeholder="e.g. Dell Inspiron 15" /></label>
          <label className="field"><span className="label">Brand</span><input value={p.brand} onChange={text('brand')} /></label>
          <label className="field"><span className="label">Model</span><input value={p.model} onChange={text('model')} /></label>
          <label className="field"><span className="label">Serial / IMEI (unknown is allowed)</span><input value={p.serial} onChange={text('serial')} /></label>
          <label className="field"><span className="label">Originally purchased</span>
            <select value={p.origin} onChange={text('origin')}><option value="elsewhere">Elsewhere</option><option value="shop">This shop</option></select></label>
          <label className="field"><span className="label">Submitted by (if not the owner)</span><input value={p.submitter} onChange={text('submitter')} /></label>
          <label className="field"><span className="label">Relationship to owner</span><input value={p.relationship} onChange={text('relationship')} /></label>
        </div>
        <div className="form" style={{ marginTop: 12 }}>
          <label className="field"><span className="label required">Reported fault</span><textarea value={p.complaint} onChange={text('complaint')} /></label>
          <label className="field"><span className="label">Visible condition / damage</span><textarea value={p.damage} onChange={text('damage')} /></label>
          <label className="field"><span className="label">Additional customer requirement</span><textarea value={p.customer_requirement} onChange={text('customer_requirement')} /></label>
          <div className="row">
            <button onClick={() => setPhotoTarget('__product__')}>Photograph product</button>
            <span className="muted small">{p.product_photos.length} product photo(s)</span>
          </div>
        </div>
      </Panel>
      <Panel title="3 · Accessories actually received">
        {!p.category_id ? <div className="muted">Choose the product category to list its usual accessories.</div> : (
          <div className="stack">
            {(accessories.data ?? []).length === 0 && <div className="muted">No accessories are set up for this category.</div>}
            {(accessories.data ?? []).map((a) => {
              const v = accessory(a.name);
              return (
                <div key={a.id} className="row">
                  <label className="check" style={{ minWidth: 180 }}><input type="checkbox" checked={v.checked} onChange={(e) => setAccessory(a.name, { checked: e.target.checked })} />{a.name}</label>
                  {v.checked && <>
                    <input type="number" min={1} style={{ width: 80 }} value={v.quantity} aria-label="Quantity" onChange={(e) => setAccessory(a.name, { quantity: Math.max(1, Number(e.target.value)) })} />
                    <input style={{ maxWidth: 200 }} placeholder="Serial / mark (optional)" value={v.serial} onChange={(e) => setAccessory(a.name, { serial: e.target.value })} />
                    <select style={{ maxWidth: 150 }} value={v.condition} onChange={(e) => setAccessory(a.name, { condition: e.target.value })}>
                      {reference.conditions.map((c) => <option key={c}>{c}</option>)}
                    </select>
                    <input style={{ maxWidth: 220 }} placeholder="Notes" value={v.notes} onChange={(e) => setAccessory(a.name, { notes: e.target.value })} />
                    <button onClick={() => setPhotoTarget(a.name)}>{v.photo_id ? 'Photo ✓' : 'Photo'}</button>
                  </>}
                </div>
              );
            })}
          </div>
        )}
      </Panel>
      <Panel title="4 · Warranty, dates and money">
        <div className="form-grid">
          {sale ? <div className="info-box">Shop sale linked: warranty dates come from the sale record{sale.warranty_end ? ' (ends ' + sale.warranty_end + ')' : ''}.</div> : <>
            <label className="field"><span className="label">Customer-reported warranty</span>
              <select value={p.warranty_status} onChange={text('warranty_status')}>
                <option value="UNKNOWN">Warranty unknown</option><option value="VALID">Valid warranty</option>
                <option value="EXPIRED">Expired warranty</option><option value="NONE">No warranty</option>
              </select></label>
            {p.warranty_status === 'VALID' && <>
              <label className="field"><span className="label">Warranty expiry</span><input type="date" min={shopToday()} value={p.warranty_expiry} onChange={text('warranty_expiry')} /></label>
              <label className="field"><span className="label">Warranty provider</span><input value={p.warranty_provider} onChange={text('warranty_provider')} /></label>
              <label className="field"><span className="label">Warranty notes</span><input value={p.warranty_notes} onChange={text('warranty_notes')} /></label>
            </>}
          </>}
          <label className="field"><span className="label">Estimated repair completion</span><input type="date" value={p.repair_due} onChange={text('repair_due')} /></label>
          <label className="field"><span className="label">Estimated customer collection</span><input type="date" value={p.collection_due} onChange={text('collection_due')} /></label>
          <label className="field"><span className="label">Agreed decline / return policy</span>
            <select value={p.policy} onChange={text('policy')}>{reference.policies.map((x) => <option key={x.value} value={x.value}>{x.label}</option>)}</select></label>
          <label className="field"><span className="label">Initial estimate (INR)</span><input inputMode="decimal" value={p.initial_estimate} onChange={text('initial_estimate')} /></label>
          <label className="field"><span className="label">Deposit required to start (INR)</span><input inputMode="decimal" value={p.deposit} onChange={text('deposit')} /></label>
          <label className="field"><span className="label">Advance received now (INR)</span><input inputMode="decimal" value={p.advance} onChange={text('advance')} /></label>
          <label className="field"><span className="label">Agreed transport charge (INR)</span><input inputMode="decimal" value={p.transport_agreed} onChange={text('transport_agreed')} /></label>
          <label className="field"><span className="label">Agreed assessment (INR)</span><input inputMode="decimal" value={p.assessment_agreed} onChange={text('assessment_agreed')} /></label>
          <label className="check"><input type="checkbox" checked={p.assessment_consent} onChange={(e) => set('assessment_consent', e.target.checked)} />Assessment / transport consent recorded</label>
        </div>
      </Panel>
      {photoTarget && <PhotoCapture title={photoTarget === '__product__' ? 'Product photo' : 'Accessory photo · ' + photoTarget} busy={capture.isPending} error={capture.error}
                                    onPhoto={(blob, name) => capture.mutate({ blob, name })} onClose={() => setPhotoTarget(null)} />}
    </>
  );
}

function IntakeResult({ result, onAnother }: { result: Received; onAnother: () => void }) {
  return (
    <div className="stack">
      <PageTitle title="Products received" subtitle={result.visit ? 'Visit ' + result.visit.number : undefined} />
      <div className="success-note">The visit is saved. Each product has its own repair job and receiving card.</div>
      <Panel title="Repair jobs">
        <div className="stack">{result.jobs.map((j) => <Link key={j.id} to={'/repairs/' + j.id}>{j.number} · {j.device}</Link>)}</div>
      </Panel>
      <Panel title="Receipts">
        <div className="row">{result.documents.map((d) => <a key={d.id} className="button" href={d.url} target="_blank" rel="noopener">{d.title}</a>)}</div>
        {result.notes.length > 0 && <div className="info-box" style={{ marginTop: 10 }}>{result.notes.join('\n')}</div>}
      </Panel>
      <div className="row"><button className="primary" onClick={onAnother}>Start another intake</button></div>
    </div>
  );
}
