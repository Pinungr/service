import { useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, operationId, qs } from '../../api/client';
import type { FormField } from '../../api/types';
import { PageTitle } from '../../app/Layout';
import { useCan } from '../../app/session';
import { FieldForm } from '../../components/FieldForm';
import { DataTable, ErrorBox, Modal } from '../../components/ui';

interface Stock {
  id: number; sku: string; name: string; brand: string; model: string; part_number: string; compatibility: string; serialized: number; serial: string; batch: string;
  category_id: number | null; supplier_id: number | null; invoice: string; purchase_date: string | null; storage: string; minimum_stock: number;
  purchase_cost?: number; customer_price: number; markup_basis_points: number | null; warranty_duration: number; warranty_unit: string;
  warranty_provider: string; warranty_terms: string; notes: string; active: number; stock: number; reserved: number; issued: number; available: number;
}

function stockFields(row: Stock | null, can: (p: string) => boolean, suppliers: { id: number; name: string }[]): FormField[] {
  const t = (key: keyof Stock, label: string, extra: Partial<FormField> = {}): FormField => ({ key, label, type: 'text', default: row?.[key] ?? '', ...extra });
  return [
    t('name', 'Part name', { required: true }), t('sku', 'SKU (generated if blank)'), t('brand', 'Brand'), t('model', 'Model'), t('part_number', 'Part number'),
    t('compatibility', 'Compatible devices / notes'), { key: 'serialized', label: 'Individually serialized unit', type: 'check', default: Boolean(row?.serialized) },
    t('serial', 'Serial (serialized units only)'), t('batch', 'Batch number'), t('invoice', 'Supplier invoice'), t('storage', 'Shelf / bin', { default: row?.storage ?? 'Stock shelf' }),
    { key: 'supplier_id', label: 'Supplier', type: 'select', default: row?.supplier_id ?? '', options: [{ value: '', label: 'Not recorded' }, ...suppliers.map((s) => ({ value: s.id, label: s.name }))] },
    { key: 'purchase_date', label: 'Purchase date', type: 'date', default: row?.purchase_date ?? '' },
    { key: 'minimum_stock', label: 'Minimum available quantity', type: 'number', default: row?.minimum_stock ?? 0 },
    ...(can('view_internal_cost') ? [{ key: 'purchase_cost', label: 'Unit purchase cost (INR)', type: 'money' as const, default: row?.purchase_cost ?? 0 }] : []),
    { key: 'customer_price', label: 'Default customer price (INR)', type: 'money', default: row?.customer_price ?? 0 },
    { key: 'warranty_duration', label: 'Default warranty duration (0 = none)', type: 'number', default: row?.warranty_duration ?? 0 },
    { key: 'warranty_unit', label: 'Warranty unit', type: 'select', default: row?.warranty_unit ?? 'months', options: ['days', 'months', 'years'].map((u) => ({ value: u, label: u })) },
    t('warranty_provider', 'Warranty provider'), { key: 'warranty_terms', label: 'Warranty coverage / exclusions', type: 'textarea', default: row?.warranty_terms ?? '' },
    { key: 'notes', label: 'Notes', type: 'textarea', default: row?.notes ?? '' }, { key: 'active', label: 'Active item', type: 'check', default: row ? Boolean(row.active) : true },
  ];
}

export function InventoryPage() {
  const can = useCan();
  const client = useQueryClient();
  const [search, setSearch] = useState('');
  const [view, setView] = useState('all');
  const [editing, setEditing] = useState<Stock | 'new' | null>(null);
  const [adjusting, setAdjusting] = useState<Stock | null>(null);
  const [selected, setSelected] = useState<Stock | null>(null);
  const op = useRef(operationId());
  const rows = useQuery({ queryKey: ['inventory', search, view], queryFn: () => api.get<Stock[]>('/inventory' + qs({ search, view })) });
  const suppliers = useQuery({ queryKey: ['contacts', 'supplier'], queryFn: () => api.get<{ id: number; name: string }[]>('/contacts?kind=supplier') });
  const movements = useQuery({ queryKey: ['stock-movements', selected?.id], queryFn: () => api.get<any[]>('/inventory/movements' + qs({ stock_id: selected?.id })), enabled: Boolean(selected) });
  const done = () => { client.invalidateQueries({ queryKey: ['inventory'] }); client.invalidateQueries({ queryKey: ['stock-movements'] }); };
  const save = useMutation({
    mutationFn: (v: Record<string, any>) => {
      const body = { ...v, supplier_id: v.supplier_id || null, purchase_date: v.purchase_date || null, minimum_stock: Number(v.minimum_stock || 0),
                     warranty_duration: Number(v.warranty_duration || 0), purchase_cost: v.purchase_cost ?? (editing !== 'new' ? (editing as Stock).purchase_cost ?? 0 : 0) };
      return editing === 'new' ? api.post('/inventory', body) : api.put(`/inventory/${(editing as Stock).id}`, body);
    },
    onSuccess: () => { setEditing(null); done(); },
  });
  const adjust = useMutation({
    mutationFn: (v: Record<string, any>) => api.post(`/inventory/${adjusting!.id}/adjust`, { ...v, quantity: Number(v.quantity), operation_id: op.current }),
    onSuccess: () => { op.current = operationId(); setAdjusting(null); done(); },
  });
  const manage = can('manage_inventory');
  return (
    <div className="stack">
      <PageTitle title="Inventory" subtitle="Track available, reserved and issued repair parts"
                 actions={manage ? <button className="primary" onClick={() => setEditing('new')}>New inventory item</button> : null} />
      <div className="row">
        <input className="grow" style={{ maxWidth: 520 }} placeholder="Part name, SKU, compatibility, brand, model…" value={search} onChange={(e) => setSearch(e.target.value)} />
        <select style={{ maxWidth: 180 }} value={view} onChange={(e) => setView(e.target.value)}><option value="all">All parts</option><option value="low">Low stock</option><option value="out">Out of stock</option></select>
      </div>
      <DataTable rows={rows.data} onOpen={setSelected} selected={selected?.id} columns={[
        { key: 'sku', label: 'SKU' }, { key: 'name', label: 'Part' }, { key: 'brand', label: 'Brand' }, { key: 'compatibility', label: 'Compatibility' },
        { key: 'stock', label: 'Stock' }, { key: 'reserved', label: 'Reserved' }, { key: 'issued', label: 'Issued' }, { key: 'available', label: 'Available' },
        ...(can('view_internal_cost') ? [{ key: 'purchase_cost', label: 'Cost', money: true }] : []), { key: 'customer_price', label: 'Price', money: true },
        { key: 'storage', label: 'Shelf' }, { key: 'active', label: 'Active', render: (r: Stock) => (r.active ? 'Yes' : 'No') }]} />
      {selected && (
        <div className="stack">
          <div className="row">
            <strong>{selected.sku} · {selected.name}</strong>
            {manage && <button onClick={() => setEditing(selected)}>Edit item / warranty defaults</button>}
            {manage && <button onClick={() => { op.current = operationId(); setAdjusting(selected); }}>Receive / adjust stock</button>}
          </div>
          <DataTable rows={movements.data} empty="No stock movements yet." columns={[{ key: 'created', label: 'When' }, { key: 'kind', label: 'Movement' },
            { key: 'quantity', label: 'Qty' }, { key: 'delta', label: 'Stock Δ' }, { key: 'reference', label: 'Reference' }, { key: 'notes', label: 'Notes' }]} />
        </div>
      )}
      {editing && (
        <Modal title="Inventory item and warranty defaults" onClose={() => setEditing(null)} wide>
          <FieldForm fields={stockFields(editing === 'new' ? null : editing, can, suppliers.data ?? [])} busy={save.isPending}
                     onSubmit={(v) => save.mutate(v)} error={<ErrorBox error={save.error} />} onCancel={() => setEditing(null)} />
        </Modal>
      )}
      {adjusting && (
        <Modal title={`Receive stock / adjust · ${adjusting.name}`} onClose={() => setAdjusting(null)}>
          <FieldForm compact busy={adjust.isPending} onSubmit={(v) => adjust.mutate(v)} error={<ErrorBox error={adjust.error} />} onCancel={() => setAdjusting(null)} fields={[
            { key: 'kind', label: 'Movement type', type: 'select', default: 'STOCK_RECEIVED', options: [
              ['Stock received', 'STOCK_RECEIVED'], ['Stock adjustment (signed)', 'STOCK_ADJUSTMENT'], ['Damaged', 'DAMAGED'], ['Scrapped', 'SCRAPPED'],
              ['Warranty replacement received', 'WARRANTY_REPLACEMENT'], ['Customer return to stock', 'CUSTOMER_RETURN']].map(([label, value]) => ({ label, value })) },
            { key: 'quantity', label: 'Quantity', type: 'number', default: 1, required: true },
            { key: 'reference', label: 'Invoice / correction reason', type: 'text', required: true }, { key: 'notes', label: 'Notes', type: 'textarea' }]} />
        </Modal>
      )}
    </div>
  );
}
