import { ReactNode, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { api, operationId } from '../../api/client';
import type { Attempt, Dispatch, FormField, RepairDetail, StoredFile } from '../../api/types';
import { useCan } from '../../app/session';
import { FieldForm } from '../../components/FieldForm';
import { TransportField, TransportValue } from '../../components/TransportField';
import { Badge, DataTable, ErrorBox, KeyValues, Loading, Modal, Panel } from '../../components/ui';
import { formatPaise, paiseToText, parseRupees } from '../../shared/money';
import { formatDate, formatDateTime, shopToday } from '../../shared/dates';
import { warrantyLabel } from '../../shared/warranty';
import { useRefreshRepair } from './RepairWorkspace';

type Props = { repair: RepairDetail };

function useTab<T>(id: number, name: string, path: string) {
  return useQuery({ queryKey: ['repair-tab', id, name], queryFn: () => api.get<T>(path) });
}

/** A button that opens a form in a modal and runs a mutation; refreshes the repair afterwards. */
function FormButton({ label, title, fields, submit, repairId, primary = false, disabled = false, intro }: {
  label: string; title?: string; fields: FormField[]; submit: (values: Record<string, any>) => Promise<unknown>;
  repairId: number; primary?: boolean; disabled?: boolean; intro?: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const refresh = useRefreshRepair(repairId);
  const run = useMutation({ mutationFn: submit, onSuccess: async () => { await refresh(); setOpen(false); } });
  return (
    <>
      <button className={primary ? 'primary' : ''} disabled={disabled} onClick={() => { run.reset(); setOpen(true); }}>{label}</button>
      {open && (
        <Modal title={title ?? label} onClose={() => setOpen(false)} wide>
          {intro}
          <FieldForm fields={fields} busy={run.isPending} onSubmit={(v) => run.mutate(v)} error={<ErrorBox error={run.error} />} onCancel={() => setOpen(false)} />
        </Modal>
      )}
    </>
  );
}

const text = (key: string, label: string, extra: Partial<FormField> = {}): FormField => ({ key, label, type: 'text', ...extra });
const area = (key: string, label: string, extra: Partial<FormField> = {}): FormField => ({ key, label, type: 'textarea', ...extra });
const money = (key: string, label: string, paise = 0, extra: Partial<FormField> = {}): FormField => ({ key, label, type: 'money', default: paise, ...extra });
const date = (key: string, label: string, value?: string | null, extra: Partial<FormField> = {}): FormField => ({ key, label, type: 'date', default: value ?? '', ...extra });
const select = (key: string, label: string, options: [string, any][], value?: any, extra: Partial<FormField> = {}): FormField =>
  ({ key, label, type: 'select', options: options.map(([l, v]) => ({ label: l, value: v })), default: value, ...extra });

// ---- Overview ---------------------------------------------------------------------

export function OverviewTab({ repair: r }: Props) {
  const d = r.record;
  const a = r.assignment;
  const visit = useTab<{ number: string; jobs: { id: number; number: string; device: string; stage: string }[] } | null>(r.id, 'visit', `/repairs/${r.id}/visit`);
  return (
    <div className="grid2">
      <Panel title="Reported problem & diagnosis">
        <KeyValues items={[
          ['Reported fault', r.complaint], ['Condition at intake', r.damage], ['Customer requirement', r.customer_requirement],
          ['Inspection', d.inspection], ['Diagnosis', d.diagnosis], ['Parts required', d.parts_required],
          ['Repair performed', d.repair_summary], ['Parts used', d.parts_used], ['Unrepaired outcome', d.unrepaired],
          ['QC', d.qc ? `${d.qc.result} · ${d.qc.notes ?? ''}` : ''], ['Repair warranty', d.repair_warranty],
        ]} />
      </Panel>
      <Panel title="Responsibility">
        {a.party ? (
          <div className="stack">
            <div className="summary-card">{a.summary || a.party}</div>
            <KeyValues items={[['External ticket / RMA', a.reference], ['Expected return', formatDate(a.expected_return ?? r.return_due)],
                               ['Instructions', a.instructions]]} />
            <div className="small muted">Shown as recorded when the repair was assigned. Directory edits change future repairs only.</div>
          </div>
        ) : <KeyValues items={[['Assigned technician', r.assigned_technician], ['Responsible', r.responsible]]} />}
      </Panel>
      <Panel title="Dates & money">
        <KeyValues items={[['Repair due', formatDate(r.repair_due)], ['Collection due', formatDate(r.collection_due)],
                           ['Expected external return', formatDate(r.return_due)], ['Initial estimate', formatPaise(r.initial_estimate)],
                           ['Deposit required', formatPaise(r.deposit)], ['Paid / retained', formatPaise(r.paid)], ['Balance', formatPaise(r.balance)]]} />
        <div className="row" style={{ marginTop: 10 }}>
          <FormButton label="Revise dates" repairId={r.id}
                      fields={[date('repair_due', 'Repair completion', r.repair_due), date('collection_due', 'Customer collection', r.collection_due),
                               date('return_due', 'External return', r.return_due), area('reason', 'Reason for estimate / revision', { required: true })]}
                      submit={(v) => api.post(`/repairs/${r.id}/dates`, { ...v, expected_version: r.version,
                        repair_due: v.repair_due || null, collection_due: v.collection_due || null, return_due: v.return_due || null })} />
          <FormButton label={r.hold_reason ? 'Release / change hold' : 'Put on hold'} repairId={r.id}
                      fields={[area('reason', 'Hold / outcome reason (clear it to release the hold)', { default: r.hold_reason })]}
                      submit={(v) => api.post(`/repairs/${r.id}/hold`, v)} />
        </div>
      </Panel>
      <Panel title="Intake warranty & visit">
        <KeyValues items={[['Warranty status', warrantyLabel(r.warranty_status)],
                           ['Reported at intake', d.intake_warranty ? `${d.intake_warranty.status ?? ''} · ${d.intake_warranty.source ?? ''}` : 'Not recorded'],
                           ['Visit', visit.data?.number ?? r.visit_number]]} />
        {visit.data && visit.data.jobs.length > 1 && (
          <div className="stack" style={{ marginTop: 8 }}>
            <div className="small muted">Other products in this visit</div>
            {visit.data.jobs.filter((j) => j.id !== r.id).map((j) => <Link key={j.id} to={'/repairs/' + j.id}>{j.number} · {j.device}</Link>)}
          </div>
        )}
      </Panel>
    </div>
  );
}

// ---- Items & custody ---------------------------------------------------------------

interface Items {
  holdings: { id: number; description: string; type: string; serial: string; location: string; quantity: number; holder: { name: string; role: string } }[];
  movements: { id: number; item: string; quantity: number; happened: string; from_holder: string; to_holder: string; counterparty: string; reference: string; acknowledgment: string }[];
}

export function ItemsTab({ repair: r }: Props) {
  const items = useTab<Items>(r.id, 'items', `/repairs/${r.id}/items`);
  return (
    <div className="stack">
      <p className="muted">Who physically holds each item. Assigning a repair partner never moves an item; only a recorded handover does.</p>
      <DataTable rows={items.data?.holdings} columns={[
        { key: 'description', label: 'Item' }, { key: 'type', label: 'Type' }, { key: 'serial', label: 'Serial' },
        { key: 'holder', label: 'Held by', render: (h) => `${h.holder.name} · ${h.holder.role}` }, { key: 'quantity', label: 'Qty' }]} />
      <h3>Handovers</h3>
      <DataTable rows={items.data?.movements} empty="No handovers recorded." columns={[
        { key: 'happened', label: 'When' }, { key: 'item', label: 'Item' }, { key: 'quantity', label: 'Qty' },
        { key: 'from_holder', label: 'From' }, { key: 'to_holder', label: 'To' }, { key: 'counterparty', label: 'Person' },
        { key: 'reference', label: 'Reference' }, { key: 'acknowledgment', label: 'Acknowledgment' }]} />
    </div>
  );
}

// ---- Dispatch ----------------------------------------------------------------------

interface DispatchOverview { current: Dispatch | null; history: Dispatch[]; attempts: Attempt[] }

function DispatchEditor({ repair, current, mode, onClose }: { repair: RepairDetail; current: Dispatch; mode: 'edit' | 'amend'; onClose: () => void }) {
  const refresh = useRefreshRepair(repair.id);
  const [transport, setTransport] = useState<TransportValue>({ mode: current.transport_mode as TransportValue['mode'], service_id: null, fields: { ...current.transport } });
  const [values, setValues] = useState({ amount: paiseToText(current.amount), paid_by: current.paid_by, reference: current.reference,
                                         expected_return: current.expected_return ?? '', notes: current.notes, reason: '' });
  const op = useState(operationId)[0];
  const save = useMutation({
    mutationFn: () => {
      const amount = parseRupees(values.amount);
      if (amount === null) throw new Error('Enter the transport charge as an amount.');
      const body = { transport_mode: transport.mode, transport: transport.fields, transporter_id: transport.service_id ?? (transport.mode === 'BUS' ? (current as any).transporter_id : null),
                     amount, paid_by: values.paid_by, reference: values.reference, expected_return: values.expected_return || null, notes: values.notes };
      return mode === 'edit' ? api.patch(`/repairs/${repair.id}/dispatch`, body)
                             : api.post(`/repairs/${repair.id}/dispatch/amend`, { values: body, reason: values.reason, operation_id: op });
    },
    onSuccess: async () => { await refresh(); onClose(); },
  });
  const set = (key: keyof typeof values) => (e: { target: { value: string } }) => setValues({ ...values, [key]: e.target.value });
  return (
    <Modal title={mode === 'edit' ? 'Edit dispatch' : 'Amend sent dispatch'} onClose={onClose} wide>
      <p className="muted">{mode === 'edit' ? 'Nothing has physically left yet, so these details are corrected in place.'
        : 'A correction creates a new dispatch version; the original record and the custody movement stay unchanged.'}</p>
      {current.transporter && <div className="info-box">Recorded bus service: {current.transporter}. Select another only to correct a wrong selection.</div>}
      <div className="form">
        <TransportField value={transport} onChange={setTransport} />
        <div className="form-grid">
          <label className="field"><span className="label">Transport charge (INR)</span><input value={values.amount} onChange={set('amount')} /></label>
          <label className="field"><span className="label">Paid by</span>
            <select value={values.paid_by} onChange={set('paid_by')}>
              {[['shop', 'Shop'], ['customer', 'Customer'], ['third_party', 'Third party'], ['service_center', 'Service center'], ['other', 'Other']]
                .map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select></label>
          <label className="field"><span className="label">Service centre ticket / external job number</span><input value={values.reference} onChange={set('reference')} /></label>
          <label className="field"><span className="label">Expected return</span><input type="date" value={values.expected_return} onChange={set('expected_return')} /></label>
        </div>
        <label className="field"><span className="label">Notes</span><textarea value={values.notes} onChange={set('notes')} /></label>
        {mode === 'amend' && <label className="field"><span className="label required">Reason for the correction</span><textarea value={values.reason} onChange={set('reason')} /></label>}
        <ErrorBox error={save.error} />
        <div className="row"><button className="primary" disabled={save.isPending} onClick={() => save.mutate()}>Save</button><button onClick={onClose}>Cancel</button></div>
      </div>
    </Modal>
  );
}

export function DispatchTab({ repair: r }: Props) {
  const data = useTab<DispatchOverview>(r.id, 'dispatch', `/repairs/${r.id}/dispatch`);
  const [editing, setEditing] = useState<'edit' | 'amend' | null>(null);
  if (!data.data) return <Loading />;
  const c = data.data.current;
  return (
    <div className="stack">
      <Panel title="Current dispatch" actions={c && <>
        {c.editable ? <button onClick={() => setEditing('edit')}>Edit dispatch</button> : <button onClick={() => setEditing('amend')}>Amend dispatch</button>}
        {c.editable && <FormButton label="Cancel dispatch" repairId={r.id} fields={[area('reason', 'Reason for cancelling', { required: true })]}
                                   submit={(v) => api.post(`/repairs/${r.id}/dispatch/cancel`, v)} />}
      </>}>
        {c ? (
          <KeyValues items={[
            ['Sent to', `${c.party ?? ''}${c.contact_snapshot.phone ? ' · ' + c.contact_snapshot.phone : ''}`],
            ['Status', <Badge tone={c.status === 'DISPATCHED' ? 'info' : 'neutral'}>{c.status} · version {c.version}</Badge>],
            ['Transport', c.transport_summary || c.transport_mode], ['Carrier', c.carrier], ['Transport charge', formatPaise(c.amount)],
            ['Reference', c.reference], ['Expected return', formatDate(c.expected_return)],
            ['Sent', c.actual_dispatch_at ? formatDateTime(c.actual_dispatch_at) : 'Not yet physically dispatched'],
            ['Correction reason', c.amendment_reason]]} />
        ) : <div className="muted">No dispatch has been prepared for this repair.</div>}
      </Panel>
      <h3>Dispatch versions</h3>
      <DataTable rows={data.data.history} rowKey="id" empty="No dispatch versions yet." columns={[
        { key: 'version', label: 'Version' }, { key: 'status', label: 'Status' }, { key: 'party', label: 'Sent to' },
        { key: 'transport_summary', label: 'Transport' }, { key: 'amount', label: 'Charge', money: true },
        { key: 'actual_dispatch_at', label: 'Sent' }, { key: 'amendment_reason', label: 'Correction' }]} />
      <h3>Repair partner history</h3>
      <DataTable rows={data.data.attempts} rowKey="attempt" empty="No external partner has been assigned." columns={[
        { key: 'attempt', label: '#' }, { key: 'partner', label: 'Partner' },
        { key: 'contact', label: 'Contact (as recorded)', render: (a) => [a.snapshot.contact_person, a.snapshot.phone].filter(Boolean).join(' · ') || '—' },
        { key: 'reference', label: 'Reference' }, { key: 'sent', label: 'Sent' }, { key: 'returned', label: 'Returned' }, { key: 'result', label: 'Result' }]} />
      {editing && c && <DispatchEditor repair={r} current={c} mode={editing} onClose={() => setEditing(null)} />}
    </div>
  );
}

// ---- Parts ---------------------------------------------------------------------------

interface Part { id: number; name: string; quantity: number; source: string; status: string; stock_state: string; procurement_status: string;
  customer_price: number; purchase_cost?: number; supplier_snapshot: string; installed_by: string; installed_at: string | null;
  warranty_duration: number; warranty_unit: string; warranty_provider: string; inventory_id: number | null; supplier_id: number | null;
  brand: string; model: string; part_number: string; serial: string; part_type: string; invoice: string; warranty_terms: string; notes: string;
  requested_by: string; request_notes: string; purchase_date: string | null }
interface StockRow { id: number; sku: string; name: string; available: number; active: number; customer_price: number }

function partFields(can: (p: string) => boolean, stock: StockRow[], suppliers: { id: number; name: string }[], part?: Part): FormField[] {
  return [
    select('source', 'Part source', [['Shop inventory', 'stock'], ['Repairing third-party technician', 'technician'], ['External supplier', 'supplier'], ['Other (explain in notes)', 'other']],
           part?.source ?? 'stock', { required: true }),
    select('inventory_id', 'Inventory item', stock.filter((s) => s.active).map((s) => [`${s.sku} · ${s.name} · ${s.available} available`, s.id]),
           part?.inventory_id ?? undefined, { show_if: { field: 'source', equals: ['stock'] } }),
    select('supplier_id', 'Supplier', suppliers.map((s) => [s.name, s.id]), part?.supplier_id ?? undefined, { show_if: { field: 'source', equals: ['supplier'] } }),
    text('name', 'Part name', { required: true, default: part?.name }), text('part_type', 'Type', { default: part?.part_type }),
    text('brand', 'Brand', { default: part?.brand }), text('model', 'Model', { default: part?.model }),
    text('part_number', 'Part number', { default: part?.part_number }), text('serial', 'Serial (one unit per serial)', { default: part?.serial }),
    { key: 'quantity', label: 'Quantity', type: 'number', default: part?.quantity ?? 1, required: true },
    ...(can('view_internal_cost') ? [money('purchase_cost', 'Internal unit purchase cost (INR)', part?.purchase_cost ?? 0)] : []),
    money('customer_price', 'Unit customer selling price (INR)', part?.customer_price ?? 0),
    text('invoice', 'Supplier invoice', { default: part?.invoice }), date('purchase_date', 'Purchase date', part?.purchase_date),
    { key: 'warranty_duration', label: 'Warranty duration (0 = none)', type: 'number', default: part?.warranty_duration ?? 0 },
    select('warranty_unit', 'Warranty unit', [['Days', 'days'], ['Months', 'months'], ['Years', 'years']], part?.warranty_unit ?? 'months'),
    text('warranty_provider', 'Warranty provider', { default: part?.warranty_provider }), area('warranty_terms', 'Warranty coverage / exclusions', { default: part?.warranty_terms }),
    text('requested_by', 'Part requested by', { default: part?.requested_by }), area('request_notes', 'Repairer requirement / diagnosis', { default: part?.request_notes }),
    area('notes', 'Source / part notes', { default: part?.notes }),
  ];
}

function partBody(v: Record<string, any>) {
  return { ...v, quantity: Number(v.quantity || 1), warranty_duration: Number(v.warranty_duration || 0), purchase_cost: v.purchase_cost ?? 0,
           inventory_id: v.source === 'stock' ? v.inventory_id || null : null, supplier_id: v.source === 'supplier' ? v.supplier_id || null : null,
           purchase_date: v.purchase_date || null };
}

export function PartsTab({ repair: r }: Props) {
  const can = useCan();
  const parts = useTab<Part[]>(r.id, 'parts', `/repairs/${r.id}/parts`);
  const stock = useQuery({ queryKey: ['inventory', ''], queryFn: () => api.get<StockRow[]>('/inventory') });
  const suppliers = useQuery({ queryKey: ['contacts', 'supplier'], queryFn: () => api.get<{ id: number; name: string }[]>('/contacts?kind=supplier') });
  const [selected, setSelected] = useState<Part | null>(null);
  const fields = (part?: Part) => partFields(can, stock.data ?? [], suppliers.data ?? [], part);
  const row = parts.data?.find((p) => p.id === selected?.id) ?? null;
  return (
    <div className="stack">
      <div className="row">
        <FormButton primary label="Add required part" repairId={r.id} fields={fields()} intro={<p className="muted">Search shop stock first. A changed part needs a revised customer approval.</p>}
                    submit={(v) => api.post(`/repairs/${r.id}/parts`, partBody(v))} />
      </div>
      <DataTable rows={parts.data} onOpen={setSelected} selected={row?.id} empty="No parts planned for this repair." columns={[
        { key: 'name', label: 'Part' }, { key: 'quantity', label: 'Qty' }, { key: 'source', label: 'Source' },
        { key: 'customer_price', label: 'Customer price', money: true }, { key: 'stock_state', label: 'Stock' },
        { key: 'procurement_status', label: 'Procurement' }, { key: 'status', label: 'Status' }, { key: 'installed_by', label: 'Installed by' }]} />
      {row && (
        <Panel title={row.name + ' · ' + row.status}>
          <div className="row">
            {row.status === 'planned' && <FormButton label="Edit" repairId={r.id} fields={fields(row)} submit={(v) => api.put(`/repairs/${r.id}/parts/${row.id}`, partBody(v))} />}
            {row.status === 'planned' && <FormButton label="Remove" repairId={r.id} fields={[area('reason', 'Reason', { required: true })]} submit={(v) => api.post(`/parts/${row.id}/remove`, v)} />}
            {row.status === 'planned' && <FormButton label="Mark installed" repairId={r.id}
              fields={[text('installed_by', 'Installed by', { default: r.responsible, required: true }), date('installed_date', 'Installation date', shopToday())]}
              submit={(v) => api.post(`/parts/${row.id}/install`, v)} />}
            {row.source === 'stock' && ['reserve', 'issue', 'return', 'release'].map((action) => (
              <FormButton key={action} label={action[0].toUpperCase() + action.slice(1) + ' stock'} repairId={r.id}
                          fields={[text('reference', 'Reservation / handover acknowledgment'), area('notes', 'Notes')]}
                          submit={(v) => api.post(`/parts/${row.id}/transfer`, { action, ...v })} />
            ))}
            {row.source === 'stock' && can('manage_inventory') && <FormButton label="Write off" repairId={r.id}
              fields={[select('action', 'Reason type', [['Damaged', 'damaged'], ['Scrapped', 'scrapped']], 'damaged'), text('reference', 'Write-off reference', { required: true }), area('notes', 'Details')]}
              submit={(v) => api.post(`/parts/${row.id}/transfer`, v)} />}
            {row.source === 'supplier' && ['order', 'receive'].map((action) => (
              <FormButton key={action} label={action === 'order' ? 'Order external part' : 'Receive external part'} repairId={r.id}
                          fields={[text('reference', 'Order / receipt reference')]} submit={(v) => api.post(`/parts/${row.id}/procure`, { action, ...v })} />
            ))}
          </div>
        </Panel>
      )}
    </div>
  );
}

// ---- Warranty ------------------------------------------------------------------------

interface WarrantyData {
  intake: Record<string, any> | null;
  warranties: { id: number; name: string; original_job: string; installed_at: string; duration: number; unit: string; expiry: string; effective_status: string; provider: string; terms: string; status: string; start_date: string; notes: string; claim_id: number | null }[];
  claims: { id: number; claim_job: string; original_job: string; part: string; complaint: string; status: string; resolution: string; new_job_id: number }[];
  manual_checks: { id: number; result: string; coverage: string; evidence_type: string; reference: string; provider: string; checked_by: string; checked_at: string }[];
}

export function WarrantyTab({ repair: r }: Props) {
  const can = useCan();
  const data = useTab<WarrantyData>(r.id, 'warranty', `/repairs/${r.id}/warranty`);
  const parts = useTab<Part[]>(r.id, 'parts', `/repairs/${r.id}/parts`);
  const [warranty, setWarranty] = useState<number | null>(null);
  const [claim, setClaim] = useState<number | null>(null);
  if (!data.data) return <Loading />;
  const w = data.data.warranties.find((x) => x.id === warranty);
  const c = data.data.claims.find((x) => x.id === claim);
  return (
    <div className="stack">
      {data.data.intake && <div className="info-box">Reported at intake: {data.data.intake.status} ({data.data.intake.source}){data.data.intake.expiry ? ' · expires ' + formatDate(data.data.intake.expiry) : ''}. Coverage must be verified before repair authorization.</div>}
      <div className="row">
        <FormButton label="Register repair warranty" repairId={r.id} fields={[
          text('name', 'Warranty description', { default: 'Repair workmanship' }), { key: 'duration', label: 'Duration', type: 'number', default: 3, required: true },
          select('unit', 'Unit', [['Days', 'days'], ['Months', 'months'], ['Years', 'years']], 'months'), date('start_date', 'Starts', shopToday(), { required: true }),
          text('provider', 'Provider', { required: true }), area('terms', 'Coverage / exclusions')]}
          submit={(v) => api.post(`/repairs/${r.id}/warranty/repair`, { ...v, duration: Number(v.duration) })} />
        <FormButton label="Manual warranty check" repairId={r.id} fields={[
          select('result', 'Verification result', [['Unverified', 'UNVERIFIED'], ['Valid', 'VALID'], ['Invalid', 'INVALID']], 'UNVERIFIED'),
          select('evidence_type', 'Evidence', ['Shop invoice', 'Warranty slip', 'Supplier invoice', 'Manufacturer warranty', 'Vendor confirmation', 'Other'].map((x) => [x, x]), 'Shop invoice'),
          select('coverage', 'Coverage', [['Manufacturer', 'manufacturer'], ['Shop part warranty', 'shop_part'], ['Shop repair warranty', 'shop_repair'], ['Supplier', 'supplier'], ['Vendor', 'vendor']], 'shop_part'),
          text('reference', 'Evidence reference number'), text('provider', 'Warranty provider'), area('notes', 'Verification findings')]}
          submit={(v) => api.post(`/repairs/${r.id}/warranty/manual-checks`, v)} />
      </div>
      <h3>Warranties on this device</h3>
      <DataTable rows={data.data.warranties} onOpen={(x) => setWarranty(x.id)} selected={warranty} empty="No part or repair warranty recorded for this device." columns={[
        { key: 'name', label: 'Warranty' }, { key: 'original_job', label: 'Job' }, { key: 'duration', label: 'Duration', render: (x) => `${x.duration} ${x.unit}` },
        { key: 'expiry', label: 'Expires', date: true }, { key: 'effective_status', label: 'Status' }, { key: 'provider', label: 'Provider' }]} />
      {w && (
        <div className="row">
          <FormButton label="Create claim on this warranty" repairId={r.id} fields={[area('complaint', 'Complaint', { default: r.complaint, required: true }),
            ...(can('correct_warranty') ? [area('override_reason', 'Expired warranty override reason (owner only)')] : [])]}
            submit={(v) => api.post(`/repairs/${r.id}/warranty/claims`, { warranty_id: w.id, ...v })} />
          {can('correct_warranty') && !w.claim_id && <FormButton label="Correct warranty (owner)" repairId={r.id} fields={[
            { key: 'duration', label: 'Duration', type: 'number', default: w.duration }, select('unit', 'Unit', [['Days', 'days'], ['Months', 'months'], ['Years', 'years']], w.unit),
            date('start_date', 'Starts', w.start_date), select('status', 'Status', [['Active', 'ACTIVE'], ['Void', 'VOID'], ['Replaced', 'REPLACED']], w.status),
            text('provider', 'Provider', { default: w.provider }), area('terms', 'Terms', { default: w.terms }), area('reason', 'Reason for correction', { required: true })]}
            submit={(v) => api.patch(`/warranties/${w.id}`, { ...v, duration: Number(v.duration) })} />}
        </div>
      )}
      <h3>Claims</h3>
      <DataTable rows={data.data.claims} onOpen={(x) => setClaim(x.id)} selected={claim} empty="No warranty claims." columns={[
        { key: 'id', label: 'Claim' }, { key: 'claim_job', label: 'Claim job' }, { key: 'original_job', label: 'Original job' },
        { key: 'part', label: 'Part' }, { key: 'status', label: 'Status' }, { key: 'resolution', label: 'Resolution' }]} />
      {c && c.new_job_id === r.id && (
        <FormButton label="Update selected claim" repairId={r.id} fields={[
          select('status', 'New status', ['OPEN', 'ACCEPTED', 'REJECTED', 'IN_REPAIR', 'REPLACED', 'COMPLETED', 'CLOSED'].map((s) => [s, s]), c.status),
          area('resolution', 'Decision / resolution', { default: c.resolution }),
          select('replacement_part_id', 'Installed replacement', [['No replacement', ''], ...((parts.data ?? []).filter((p) => p.status === 'installed').map((p) => [p.name, p.id] as [string, number]))], '')]}
          submit={(v) => api.patch(`/warranty-claims/${c.id}`, { ...v, replacement_part_id: v.replacement_part_id || null })} />
      )}
      <h3>Manual warranty checks</h3>
      <DataTable rows={data.data.manual_checks} empty="No manual checks recorded." columns={[
        { key: 'result', label: 'Result' }, { key: 'coverage', label: 'Coverage' }, { key: 'evidence_type', label: 'Evidence' },
        { key: 'reference', label: 'Reference' }, { key: 'checked_by', label: 'Checked by' }, { key: 'checked_at', label: 'When' }]} />
    </div>
  );
}

// ---- Quotes & payments -------------------------------------------------------------------

interface QuoteRow { id: number; version: number; state: string; scope: string; total: number; valid_until: string | null; decision: string | null }
interface QuoteDetail { id: number; version: number; total: number; scope: string; terms: string; valid_until: string | null; expired: boolean;
  categories: string[]; lines: Record<string, { description: string; amount: number }[]>; totals: Record<string, number>;
  advance: number; other_payments: number; expected_balance: number; initial_estimate: number; decisions: string[] }
interface Preview { total: number; previous_approved: number | null; change: number | null; new_parts: { description: string; amount: number }[] }

function QuoteIssuer({ repair, onClose }: { repair: RepairDetail; onClose: () => void }) {
  const refresh = useRefreshRepair(repair.id);
  const [scope, setScope] = useState('');
  const [lines, setLines] = useState([{ description: 'Repair labour', amount: '0' }]);
  const [terms, setTerms] = useState('Paid work starts after this version is approved and the required deposit is received.');
  const [expiry, setExpiry] = useState('');
  const parsed = lines.filter((l) => l.description.trim()).map((l) => ({ description: l.description.trim(), amount: parseRupees(l.amount) }));
  const valid = parsed.every((l) => l.amount !== null);
  const preview = useQuery({
    queryKey: ['quote-preview', repair.id, JSON.stringify(parsed)],
    queryFn: () => api.post<Preview>(`/repairs/${repair.id}/quotes/preview`, { lines: parsed }),
    enabled: valid,
  });
  const issue = useMutation({
    mutationFn: () => api.post(`/repairs/${repair.id}/quotes`, { scope, lines: parsed, terms, valid_until: expiry || null }),
    onSuccess: async () => { await refresh(); onClose(); },
  });
  return (
    <Modal title="Issue versioned quotation" onClose={onClose} wide>
      <div className="form">
        <p className="muted">Planned parts are added automatically. Enter labour and other customer charges; discounts use a negative amount.</p>
        <label className="field"><span className="label required">Work scope</span><textarea value={scope} onChange={(e) => setScope(e.target.value)} /></label>
        {lines.map((line, i) => (
          <div key={i} className="row">
            <input className="grow" placeholder="Description" value={line.description} onChange={(e) => setLines(lines.map((l, j) => j === i ? { ...l, description: e.target.value } : l))} />
            <input style={{ width: 140 }} inputMode="decimal" value={line.amount} onChange={(e) => setLines(lines.map((l, j) => j === i ? { ...l, amount: e.target.value } : l))} />
            <button type="button" onClick={() => setLines(lines.filter((_, j) => j !== i))}>Remove</button>
          </div>
        ))}
        <div><button type="button" onClick={() => setLines([...lines, { description: '', amount: '0' }])}>+ Add charge</button></div>
        <div className="info-box">
          {!valid ? 'Enter each amount as a number, for example 1250.50.' : preview.data ? <>
            {preview.data.previous_approved !== null && <>Previous approved amount: {formatPaise(preview.data.previous_approved)}{'\n'}</>}
            Newly quoted parts: {preview.data.new_parts.map((p) => `${p.description} · ${formatPaise(p.amount)}`).join('; ') || 'None'}{'\n'}
            Total: {formatPaise(preview.data.total)}{preview.data.change !== null ? `\nChange from previous approval: ${formatPaise(preview.data.change)}` : ''}{'\n'}
            This quotation requires the customer's explicit decision.</> : 'Calculating…'}
        </div>
        <label className="field"><span className="label">Terms</span><textarea value={terms} onChange={(e) => setTerms(e.target.value)} /></label>
        <label className="field"><span className="label">Valid through (optional)</span><input type="date" min={shopToday()} value={expiry} onChange={(e) => setExpiry(e.target.value)} /></label>
        <ErrorBox error={issue.error} />
        <div className="row"><button className="primary" disabled={!valid || !scope.trim() || issue.isPending} onClick={() => issue.mutate()}>Issue quotation</button><button onClick={onClose}>Cancel</button></div>
      </div>
    </Modal>
  );
}

export function QuoteDecision({ quoteId, onClose, onDone }: { quoteId: number; onClose: () => void; onDone: () => void }) {
  const q = useQuery({ queryKey: ['quote', quoteId], queryFn: () => api.get<QuoteDetail>('/quotes/' + quoteId) });
  const decide = useMutation({ mutationFn: (v: Record<string, any>) => api.post(`/quotes/${quoteId}/decision`, v), onSuccess: onDone });
  if (!q.data) return <Modal title="Customer decision" onClose={onClose}><Loading /></Modal>;
  const d = q.data;
  return (
    <Modal title={`Record customer decision · version ${d.version}`} onClose={onClose} wide>
      <div className="stack">
        <div className="muted">{d.valid_until ? (d.expired ? 'EXPIRED on ' : 'Valid through ') + formatDate(d.valid_until) : 'No expiry date'} · Sending or reading a message is not approval.</div>
        <div className="info-box mono">
          {d.categories.filter((k) => d.lines[k]?.length).map((k) => `${k.toUpperCase()}\n` + d.lines[k].map((l) => `  ${l.description} — ${formatPaise(l.amount)}`).join('\n') + `\n  ${k} total ${formatPaise(d.totals[k])}`).join('\n\n')}
          {`\n\nTOTAL APPROVAL VALUE ${formatPaise(d.total)}\nAdvance already paid ${formatPaise(d.advance)}\nOther payments ${formatPaise(d.other_payments)}\nExpected balance ${formatPaise(d.expected_balance)}\nInitial estimate at intake ${formatPaise(d.initial_estimate)}`}
        </div>
        {d.expired && <div className="notice">You can record a decline. For approval, issue a revised quotation.</div>}
        <FieldForm fields={[select('decision', 'Decision', d.decisions.map((x) => [x[0].toUpperCase() + x.slice(1), x]), d.decisions[0], { required: true }),
                            text('person', 'Customer / authorized representative', { required: true }),
                            select('channel', 'Received via', [['Call', 'call'], ['In person', 'in_person'], ['WhatsApp', 'whatsapp'], ['Email', 'email']], 'in_person', { required: true }),
                            area('evidence', 'Evidence / conversation reference')]}
                   busy={decide.isPending} onSubmit={(v) => decide.mutate(v)} error={<ErrorBox error={decide.error} />} onCancel={onClose} />
      </div>
    </Modal>
  );
}

interface BillingSummary { initial_estimate: number; approved_total: number | null; final_bill: number; advance: number; other_payments: number; balance_due: number }

export function QuotesTab({ repair: r }: Props) {
  const can = useCan();
  const client = useQueryClient();
  const refresh = useRefreshRepair(r.id);
  const quotes = useTab<QuoteRow[]>(r.id, 'quotes', `/repairs/${r.id}/quotes`);
  const billing = useTab<BillingSummary>(r.id, 'billing', `/repairs/${r.id}/billing`);
  const [issuing, setIssuing] = useState(false);
  const [deciding, setDeciding] = useState<number | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const invoice = useMutation({ mutationFn: (id: number) => api.post(`/quotes/${id}/invoice`, { operation_id: operationId() }), onSuccess: refresh });
  const print = useMutation({ mutationFn: (id: number) => api.post<StoredFile>(`/repairs/${r.id}/documents`, { kind: 'quotation', source_id: id }),
                              onSuccess: (f) => window.open(f.url, '_blank', 'noopener') });
  const b = billing.data;
  return (
    <div className="stack">
      <div className="row">
        {can('create_quote') && <button className="primary" onClick={() => setIssuing(true)}>+ Issue quotation</button>}
        {selected && can('approve_quote') && <button onClick={() => setDeciding(selected)}>Record customer decision</button>}
        {selected && can('billing') && <button onClick={() => invoice.mutate(selected)}>Issue customer bill</button>}
        {selected && <button onClick={() => print.mutate(selected)}>Print quotation</button>}
      </div>
      <ErrorBox error={invoice.error || print.error} />
      <DataTable rows={quotes.data} onOpen={(q) => setSelected(q.id)} selected={selected} empty="No quotation issued yet." columns={[
        { key: 'version', label: 'Version' }, { key: 'state', label: 'State' }, { key: 'decision', label: 'Decision' },
        { key: 'scope', label: 'Scope' }, { key: 'total', label: 'Total', money: true }, { key: 'valid_until', label: 'Valid until', date: true }]} />
      {b && (
        <Panel title="Money position">
          <KeyValues items={[['Initial estimate', formatPaise(b.initial_estimate)], ['Approved quote', b.approved_total === null ? 'Not approved' : formatPaise(b.approved_total)],
                             ['Final bill', b.final_bill ? formatPaise(b.final_bill) : 'Not billed yet'], ['Advance paid', formatPaise(b.advance)],
                             ['Other payments', formatPaise(b.other_payments)], ['Balance due', formatPaise(b.balance_due)]]} />
          <div className="row" style={{ marginTop: 10 }}>
            {can('collect_payment') && <FormButton label="Record customer payment / refund" repairId={r.id} fields={[
              select('kind', 'Entry type', can('correct_finance') ? [['Receipt', 'receipt'], ['Refund', 'refund']] : [['Receipt', 'receipt']], 'receipt', { required: true }),
              money('amount', 'Amount (INR)', Math.max(0, b.balance_due), { required: true }), text('method', 'Payment method', { default: 'Cash' }),
              text('reference', 'Invoice / UPI / bank / receipt reference'), area('notes', 'Notes')]}
              submit={(v) => api.post('/accounts/customer/entries', { ...v, account_id: r.customer_id, job_id: r.id })} />}
            {r.vendor_payments && r.assignment.contact_id && <FormButton label="Third-party invoice / payment" repairId={r.id} fields={[
              select('kind', 'Entry type', [['Charge', 'charge'], ['Payment', 'payment'], ['Refund', 'refund'], ['Credit', 'credit']], 'charge', { required: true }),
              money('amount', 'Amount (INR)', 0, { required: true }), text('method', 'Payment method'), text('reference', 'Invoice / reference'), area('notes', 'Notes')]}
              submit={(v) => api.post('/accounts/vendor/entries', { ...v, account_id: r.assignment.contact_id, job_id: r.id })} />}
          </div>
        </Panel>
      )}
      {can('view_internal_cost') && r.route !== 'in_house' && <PartyQuotes repair={r} />}
      {issuing && <QuoteIssuer repair={r} onClose={() => setIssuing(false)} />}
      {deciding && <QuoteDecision quoteId={deciding} onClose={() => setDeciding(null)} onDone={async () => { setDeciding(null); await refresh(); client.invalidateQueries({ queryKey: ['quotes'] }); }} />}
    </div>
  );
}

function PartyQuotes({ repair: r }: Props) {
  const data = useTab<{ current: any; history: any[] }>(r.id, 'party-quotes', `/repairs/${r.id}/party-quotes`);
  return (
    <Panel title="Third-party quotation (internal)" actions={<FormButton label="Record third-party quotation" repairId={r.id} fields={[
      money('labour', 'Labour (INR)'), money('transport', 'Transport charged by third party (INR)'), money('other', 'Other (INR)'),
      text('reference', 'Third-party quotation reference'), area('notes', 'Notes'), text('reason', 'Revision reason (when revising)')]}
      submit={(v) => api.post(`/repairs/${r.id}/party-quotes`, { ...v, lines: [] })} />}>
      {data.data?.current ? <KeyValues items={[['Version', data.data.current.version], ['Total', formatPaise(data.data.current.total)],
                                               ['Reference', data.data.current.reference]]} /> : <div className="muted">No third-party quotation recorded.</div>}
    </Panel>
  );
}

// ---- Documents --------------------------------------------------------------------------

interface AttachmentRow { id: number; kind: string; title: string; created: string }
interface Card { id: number; number: string; kind: string; from_name: string; to_name: string; effective: string }

const DOCUMENTS: [string, string][] = [['intake_receipt', 'Receiving job card'], ['dispatch_manifest', 'Dispatch card'], ['return_manifest', 'Return card'],
  ['collection_receipt', 'Collection receipt'], ['warranty_summary', 'Warranty summary'], ['final_invoice', 'Final invoice']];

export function DocumentsTab({ repair: r }: Props) {
  const can = useCan();
  const refresh = useRefreshRepair(r.id);
  const attachments = useTab<AttachmentRow[]>(r.id, 'attachments', `/repairs/${r.id}/attachments`);
  const cards = useTab<Card[]>(r.id, 'cards', `/repairs/${r.id}/cards`);
  const [title, setTitle] = useState('Evidence');
  const open = (f: StoredFile) => window.open(f.url, '_blank', 'noopener');
  const generate = useMutation({ mutationFn: (kind: string) => api.post<StoredFile>(`/repairs/${r.id}/documents`, { kind }), onSuccess: async (f) => { open(f); await refresh(); } });
  const printCard = useMutation({ mutationFn: ({ id, internal }: { id: number; internal: boolean }) => api.post<StoredFile>(`/cards/${id}/print`, { internal }), onSuccess: open });
  const upload = useMutation({
    mutationFn: (file: File) => { const form = new FormData(); form.append('file', file); form.append('title', title); return api.upload<StoredFile>(`/repairs/${r.id}/attachments`, form); },
    onSuccess: refresh,
  });
  return (
    <div className="stack">
      <Panel title="Create document">
        <div className="row">{DOCUMENTS.map(([kind, label]) => <button key={kind} onClick={() => generate.mutate(kind)} disabled={generate.isPending}>{label}</button>)}</div>
        <ErrorBox error={generate.error} />
      </Panel>
      <Panel title="Attach evidence (PDF, JPG or PNG)">
        <div className="row">
          <input style={{ maxWidth: 260 }} value={title} onChange={(e) => setTitle(e.target.value)} aria-label="Evidence title" />
          <input type="file" accept="application/pdf,image/jpeg,image/png" style={{ maxWidth: 320 }}
                 onChange={(e) => { const f = e.target.files?.[0]; if (f) upload.mutate(f); e.target.value = ''; }} />
        </div>
        <ErrorBox error={upload.error} />
      </Panel>
      <h3>Files</h3>
      <DataTable rows={attachments.data} onOpen={(a) => window.open('/api/files/' + a.id, '_blank', 'noopener')} empty="No files yet." columns={[
        { key: 'title', label: 'Title' }, { key: 'kind', label: 'Kind' }, { key: 'created', label: 'Created' }]} />
      <h3>Issued job cards</h3>
      <DataTable rows={cards.data} empty="No job cards issued." columns={[
        { key: 'number', label: 'Card' }, { key: 'kind', label: 'Type' }, { key: 'from_name', label: 'From' }, { key: 'to_name', label: 'To' },
        { key: 'effective', label: 'Effective' },
        { key: 'print', label: '', render: (c) => <div className="row">
          <button onClick={() => printCard.mutate({ id: c.id, internal: false })}>Print</button>
          {can('view_internal_cost') && <button onClick={() => printCard.mutate({ id: c.id, internal: true })}>Internal copy</button>}</div> }]} />
    </div>
  );
}

// ---- Timeline & costing -------------------------------------------------------------------

export function TimelineTab({ repair: r }: Props) {
  const rows = useTab<{ id: number; created: string; actor: string | null; event: string; details: string }[]>(r.id, 'timeline', `/repairs/${r.id}/timeline`);
  return <DataTable rows={rows.data ? [...rows.data].reverse() : undefined} columns={[
    { key: 'created', label: 'When' }, { key: 'event', label: 'Event' }, { key: 'actor', label: 'By' }, { key: 'details', label: 'Details' }]} />;
}

const COSTS: [string, string][] = [['vendor_labour', 'Vendor labour'], ['transport_cost', 'Transport'], ['other_cost', 'Other'],
  ['service_center_charge', 'Service centre charge'], ['in_house_cost', 'In-house cost']];

export function CostingTab({ repair: r }: Props) {
  const costs = useTab<Record<string, number>>(r.id, 'costs', `/repairs/${r.id}/costs`);
  if (!costs.data) return <Loading />;
  return (
    <div className="stack">
      <p className="muted">Internal budget. Part costs come from the Parts tab; posted vendor bills stay in Vendor accounts. Customers never see these figures.</p>
      <DataTable rows={Object.entries(costs.data).filter(([, v]) => typeof v === 'number').map(([k, v]) => ({ id: k, component: k.replace(/_/g, ' '), amount: v }))}
                 columns={[{ key: 'component', label: 'Component' }, { key: 'amount', label: 'Amount', money: true }]} />
      <div><FormButton label="Update internal costs" repairId={r.id} fields={[...COSTS.map(([k, l]) => money(k, l + ' (INR)', costs.data[k] ?? 0)), text('reason', 'Costing reference / reason', { required: true })]}
                       submit={(v) => { const { reason, ...values } = v; return api.put(`/repairs/${r.id}/costs`, { values, reason }); }} /></div>
    </div>
  );
}
