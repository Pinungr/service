import { useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useParams } from 'react-router-dom';
import { api, ApiError, operationId } from '../../api/client';
import type { ActionForm, ActionRef, ActionResult, Journey, RepairDetail, StoredFile } from '../../api/types';
import { PageTitle } from '../../app/Layout';
import { useCan } from '../../app/session';
import { FieldForm } from '../../components/FieldForm';
import { Badge, ErrorBox, KeyValues, Loading, Modal, Panel, Tabs, statusTone } from '../../components/ui';
import { formatPaise } from '../../shared/money';
import { formatDate, formatDateTime } from '../../shared/dates';
import { warrantyLabel } from '../../shared/warranty';
import { JourneyBar } from './JourneyBar';
import {
  CostingTab, DispatchTab, DocumentsTab, ItemsTab, OverviewTab, PartsTab, QuotesTab, TimelineTab, WarrantyTab,
} from './RepairTabs';

type TabKey = 'overview' | 'items' | 'dispatch' | 'parts' | 'warranty' | 'quotes' | 'documents' | 'timeline' | 'costing';
const NAVIGATE: Record<string, TabKey> = { quotes: 'quotes', payments: 'quotes', parts: 'parts', warranty: 'warranty', costing: 'costing' };

export function useRepair(id: number) {
  return useQuery({ queryKey: ['repair', id], queryFn: () => api.get<RepairDetail>('/repairs/' + id) });
}

export function useRefreshRepair(id: number) {
  const client = useQueryClient();
  return () => Promise.all([
    client.invalidateQueries({ queryKey: ['repair', id] }),
    client.invalidateQueries({ queryKey: ['journey', id] }),
    client.invalidateQueries({ queryKey: ['repair-tab', id] }),
    client.invalidateQueries({ queryKey: ['dashboard'] }),
    client.invalidateQueries({ queryKey: ['repairs'] }),
  ]);
}

export function RepairWorkspace() {
  const id = Number(useParams().repairId);
  const can = useCan();
  const repair = useRepair(id);
  const journey = useQuery({ queryKey: ['journey', id], queryFn: () => api.get<Journey>(`/repairs/${id}/journey`) });
  const [tab, setTab] = useState<TabKey>('overview');
  const [modalAction, setModalAction] = useState<ActionRef | null>(null);
  if (repair.error) return <ErrorBox error={repair.error} />;
  if (!repair.data) return <Loading />;
  const r = repair.data;
  const primary = r.actions.find((a) => a.primary);
  const others = r.actions.filter((a) => !a.primary);
  const tabs: { key: TabKey; label: string }[] = [
    { key: 'overview', label: 'Overview' }, { key: 'items', label: 'Items & custody' },
    ...(r.route !== 'in_house' || r.assignment.contact_id ? [{ key: 'dispatch' as TabKey, label: 'Dispatch' }] : []),
    { key: 'parts', label: 'Parts' }, { key: 'warranty', label: 'Warranty' }, { key: 'quotes', label: 'Quotes & payments' },
    { key: 'documents', label: 'Documents' }, { key: 'timeline', label: 'Timeline' },
    ...(can('view_internal_cost') ? [{ key: 'costing' as TabKey, label: 'Internal costing' }] : []),
  ];
  const openAction = (action: ActionRef) => {
    if (NAVIGATE_ACTIONS[action.key]) setTab(NAVIGATE_ACTIONS[action.key]);
    else setModalAction(action);
  };

  return (
    <div className="stack">
      <PageTitle title={`${r.number} · ${r.device}`} subtitle={`${r.customer} · ${r.phone}${r.device_id ? ' · DEV-' + String(r.device_id).padStart(6, '0') : ''}`} />
      <Panel>
        <div className="grid2">
          <KeyValues items={[
            ['Repair route', r.route_label], ['Status', <Badge tone={statusTone(r.current_status)}>{r.current_status}</Badge>],
            ['Warranty', warrantyLabel(r.warranty_status)], ['Received by', r.received_by],
          ]} />
          <KeyValues items={[
            ['Responsible for repair', r.responsible],
            ['Currently with', `${r.current_custodian}${r.custodian_role ? ' · ' + r.custodian_role : ''}${r.custodian_since ? '\nSince ' + formatDateTime(r.custodian_since) : ''}`],
            ['Physical location', r.current_location], ['Balance', formatPaise(r.balance)],
          ]} />
        </div>
        {r.attention.length > 0 && <div className="notice" style={{ marginTop: 10 }}>{r.attention.join(' · ')}</div>}
        {r.hold_reason && <div className="error" style={{ marginTop: 10 }}>On hold: {r.hold_reason}</div>}
      </Panel>
      <Panel title="Repair journey">
        {journey.data ? <JourneyBar journey={journey.data} /> : <Loading />}
      </Panel>
      <Panel title="Next step">
        <div className="muted" style={{ marginBottom: 10 }}>{r.next_action}</div>
        {primary ? <ActionRunner key={primary.key + r.version} repair={r} action={primary} inline onNavigate={(t) => setTab(t)} />
                 : <div className="muted">No action is required from the shop right now.</div>}
        {others.length > 0 && (
          <div className="stack" style={{ marginTop: 14 }}>
            {(['step', 'tool', 'exception'] as const).map((group) => {
              const list = others.filter((a) => a.group === group);
              if (!list.length) return null;
              return (
                <div key={group} className="row">
                  <span className="small muted" style={{ minWidth: 110 }}>{group === 'step' ? 'Other actions' : group === 'tool' ? 'Tools' : 'Corrections'}</span>
                  {list.map((a) => <button key={a.key} onClick={() => openAction(a)}>{a.label}</button>)}
                </div>
              );
            })}
          </div>
        )}
      </Panel>
      <div>
        <Tabs tabs={tabs} value={tab} onChange={setTab} />
        {tab === 'overview' && <OverviewTab repair={r} />}
        {tab === 'items' && <ItemsTab repair={r} />}
        {tab === 'dispatch' && <DispatchTab repair={r} />}
        {tab === 'parts' && <PartsTab repair={r} />}
        {tab === 'warranty' && <WarrantyTab repair={r} />}
        {tab === 'quotes' && <QuotesTab repair={r} />}
        {tab === 'documents' && <DocumentsTab repair={r} />}
        {tab === 'timeline' && <TimelineTab repair={r} />}
        {tab === 'costing' && <CostingTab repair={r} />}
      </div>
      {modalAction && (
        <Modal title={modalAction.label} onClose={() => setModalAction(null)} wide>
          <ActionRunner repair={r} action={modalAction} onDone={() => setModalAction(null)} onNavigate={(t) => { setModalAction(null); setTab(t); }} />
        </Modal>
      )}
      <div className="small muted">Received {formatDateTime(r.received)} · Visit {r.visit_number ?? '—'} · {r.current_card} · {r.warranty_indicator}
        {r.repair_due ? ' · Repair due ' + formatDate(r.repair_due) : ''}{r.collection_due ? ' · Collection due ' + formatDate(r.collection_due) : ''}</div>
    </div>
  );
}

const NAVIGATE_ACTIONS: Record<string, TabKey> = { quote: 'quotes', decision: 'quotes', payment: 'quotes', parts: 'parts', manual_warranty: 'warranty', costing: 'costing', claim: 'warranty' };

/**
 * Runs one guided step: asks the backend what to collect, shows only those fields, and
 * submits with the version last read and a stable operation id (so a retry is applied once).
 */
export function ActionRunner({ repair, action, inline = false, onDone, onNavigate }: {
  repair: RepairDetail; action: ActionRef; inline?: boolean; onDone?: () => void; onNavigate?: (tab: TabKey) => void;
}) {
  const refresh = useRefreshRepair(repair.id);
  const op = useRef(operationId());
  const [confirming, setConfirming] = useState<Record<string, unknown> | null>(null);
  const [notice, setNotice] = useState('');
  const form = useQuery({
    queryKey: ['action-form', repair.id, action.key, repair.version],
    queryFn: () => api.get<ActionForm>(`/repairs/${repair.id}/actions/${action.key}/form`),
    enabled: !NAVIGATE_ACTIONS[action.key],
  });
  const run = useMutation({
    mutationFn: (payload: Record<string, unknown>) =>
      api.post<ActionResult>(`/repairs/${repair.id}/actions/${action.key}`, { expected_version: repair.version, operation_id: op.current, payload }),
    onSuccess: async () => {
      if (action.key === 'handover') {
        const receipt = await api.post<StoredFile>(`/repairs/${repair.id}/documents`, { kind: 'collection_receipt' }).catch(() => null);
        if (receipt) window.open(receipt.url, '_blank', 'noopener');
      }
      op.current = operationId();
      await refresh();
      onDone?.();
    },
    onError: async (error) => {
      if (error instanceof ApiError && error.needsRefresh) {
        setNotice('This repair was updated by someone else. The latest state is shown; review it before continuing.');
        await refresh();
      }
    },
  });
  if (NAVIGATE_ACTIONS[action.key]) {
    return <button className="primary" onClick={() => onNavigate?.(NAVIGATE_ACTIONS[action.key])}>{action.label}</button>;
  }
  if (form.error) return <ErrorBox error={form.error} />;
  if (!form.data) return <Loading />;
  const f = form.data;
  if (f.navigate && NAVIGATE[f.navigate]) {
    return <button className="primary" onClick={() => onNavigate?.(NAVIGATE[f.navigate!])}>{f.title}</button>;
  }
  const submit = (payload: Record<string, unknown>) => (f.confirm ? setConfirming(payload) : run.mutate(payload));
  return (
    <div className="stack">
      {!inline && f.description && <div className="muted">{f.description}</div>}
      {notice && <div className="notice">{notice}</div>}
      {f.fields.length === 0 ? (
        <div className="row">
          <button className="primary" disabled={run.isPending} onClick={() => submit({})}>{run.isPending ? 'Saving…' : f.submit_label}</button>
          <ErrorBox error={run.error} />
        </div>
      ) : (
        <FieldForm fields={f.fields} submitLabel={f.submit_label} busy={run.isPending} onSubmit={submit}
                   error={<ErrorBox error={run.error} />} onCancel={onDone} />
      )}
      {confirming && (
        <Modal title={f.title} onClose={() => setConfirming(null)} footer={<>
          <button className="primary" onClick={() => { run.mutate(confirming); setConfirming(null); }}>Continue</button>
          <button onClick={() => setConfirming(null)}>Cancel</button>
        </>}>
          <p>{f.confirm}</p>
          {action.key === 'change_route' && <p className="muted">Currently: {repair.route_label} · {repair.responsible}</p>}
        </Modal>
      )}
    </div>
  );
}
