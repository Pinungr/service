import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../../api/client';
import { PageTitle } from '../../app/Layout';
import { DataTable, ErrorBox, Modal } from '../../components/ui';

interface Backup { id: number; name: string; kind: string; created: string; state: string; external_state: string; error: string }
interface Listing { backups: Backup[]; retention: number; archive_days: number; external_configured: boolean }

/** Backups are made, checked and restored by the backend; the browser only chooses. */
export function BackupsPage() {
  const client = useQueryClient();
  const data = useQuery({ queryKey: ['backups'], queryFn: () => api.get<Listing>('/backups') });
  const [selected, setSelected] = useState<Backup | null>(null);
  const [restoring, setRestoring] = useState(false);
  const [confirmation, setConfirmation] = useState('');
  const refresh = () => client.invalidateQueries({ queryKey: ['backups'] });
  const create = useMutation({ mutationFn: (kind: 'daily' | 'archive') => api.post('/backups', { kind }), onSuccess: refresh });
  const validate = useMutation({ mutationFn: (id: number) => api.post<{ created: string; schema: number; customers: number; jobs: number; files: number }>(`/backups/${id}/validate`) });
  const restore = useMutation({ mutationFn: () => api.post<{ restart_required: boolean }>(`/backups/${selected!.id}/restore`, { confirmation }) });
  const external = useMutation({ mutationFn: () => api.post('/backups/retry-external'), onSuccess: refresh });
  return (
    <div className="stack">
      <PageTitle title="Backups" subtitle={data.data ? `Daily recovery copies: ${data.data.retention} kept. Long-term archives every ${data.data.archive_days} days, never deleted automatically.` : ''}
                 actions={<>
                   <button className="primary" disabled={create.isPending} onClick={() => create.mutate('daily')}>{create.isPending ? 'Working…' : 'Backup now'}</button>
                   <button disabled={create.isPending} onClick={() => create.mutate('archive')}>Create long-term archive</button>
                   {data.data?.external_configured && <button onClick={() => external.mutate()}>Retry external-drive copies</button>}
                 </>} />
      <ErrorBox error={create.error || external.error} />
      <DataTable rows={data.data?.backups} onOpen={(b) => { setSelected(b); validate.reset(); restore.reset(); }} selected={selected?.id} columns={[
        { key: 'created', label: 'Created' }, { key: 'kind', label: 'Kind' }, { key: 'state', label: 'State' }, { key: 'external_state', label: 'External copy' },
        { key: 'name', label: 'File' }, { key: 'error', label: 'Problem' }]} />
      {selected && selected.state === 'verified' && (
        <div className="row">
          <button onClick={() => validate.mutate(selected.id)}>Validate archive</button>
          <button className="danger" onClick={() => { setConfirmation(''); setRestoring(true); }}>Restore this backup…</button>
          {validate.data && <span className="success-note">Verified · schema {validate.data.schema} · {validate.data.customers} customers · {validate.data.jobs} jobs · {validate.data.files} files</span>}
          <ErrorBox error={validate.error} />
        </div>
      )}
      {restoring && selected && <Modal title="Restore database and attachments" onClose={() => setRestoring(false)}>
        {restore.data ? <div className="success-note">Restore complete. Close and reopen RepairShop Manager, then sign in with the restored accounts.</div> : <>
          <p>This replaces live shop data with the backup from {selected.created}. A safety copy of the current data is kept. Outgoing messages stay paused.</p>
          <label className="field"><span className="label required">Type RESTORE to confirm</span><input value={confirmation} onChange={(e) => setConfirmation(e.target.value)} /></label>
          <ErrorBox error={restore.error} />
          <div className="row" style={{ marginTop: 10 }}>
            <button className="danger" disabled={confirmation !== 'RESTORE' || restore.isPending} onClick={() => restore.mutate()}>Restore</button>
            <button onClick={() => setRestoring(false)}>Cancel</button>
          </div></>}
      </Modal>}
    </div>
  );
}
