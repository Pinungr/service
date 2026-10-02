import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../../api/client';
import type { FormField } from '../../api/types';
import { PageTitle } from '../../app/Layout';
import { useCan } from '../../app/session';
import { FieldForm } from '../../components/FieldForm';
import { DataTable, ErrorBox, Loading, Modal, Panel, Tabs } from '../../components/ui';

interface AppSection { section: string; settings: { key: string; label: string; kind: string; choices: string[]; value: unknown }[] }
interface StaffRow { id: number; username: string; name: string; role: string; active: number }

export function SettingsPage() {
  const can = useCan();
  const [tab, setTab] = useState<'shop' | 'application' | 'staff' | 'messaging' | 'system'>('shop');
  return (
    <div className="stack">
      <PageTitle title="Settings & staff" subtitle="Configure once; normal work then uses these automatically." />
      <Tabs tabs={[{ key: 'shop', label: 'Shop & backup' }, { key: 'application', label: 'Business & application' },
                   ...(can('user_management') ? [{ key: 'staff' as const, label: 'Staff logins' }] : []),
                   ...(can('messaging_admin') ? [{ key: 'messaging' as const, label: 'Messaging' }] : []), { key: 'system', label: 'Application' }]} value={tab} onChange={setTab} />
      {tab === 'shop' && <ShopSettings />}
      {tab === 'application' && <ApplicationSettings />}
      {tab === 'staff' && <Staff />}
      {tab === 'messaging' && <Messaging />}
      {tab === 'system' && <SystemPanel />}
    </div>
  );
}

function ShopSettings() {
  const client = useQueryClient();
  const data = useQuery({ queryKey: ['settings-shop'], queryFn: () => api.get<Record<string, any>>('/settings/shop') });
  const save = useMutation({ mutationFn: (v: Record<string, any>) => api.put('/settings/shop', { ...v, backup_retention: Number(v.backup_retention), archive_days: Number(v.archive_days) }),
                             onSuccess: () => { client.invalidateQueries({ queryKey: ['settings-shop'] }); client.invalidateQueries({ queryKey: ['me'] }); } });
  if (!data.data) return <Loading />;
  const d = data.data;
  const fields: FormField[] = [
    { key: 'shop_name', label: 'Shop name', type: 'text', default: d.shop_name, required: true }, { key: 'address', label: 'Shop address', type: 'textarea', default: d.address },
    { key: 'hours', label: 'Opening hours', type: 'text', default: d.hours }, { key: 'timezone', label: 'Shop timezone', type: 'text', default: d.timezone },
    { key: 'decline_policy', label: 'Default return policy for new jobs', type: 'select', default: d.decline_policy, options: [
      { value: 'NO_CUSTOMER_CHARGE', label: 'No customer charge' }, { value: 'AGREED_TRANSPORT_ONLY', label: 'Agreed transport only' }] },
    { key: 'backup_destination', label: 'Recovery backup folder (on this computer)', type: 'text', default: d.backup_destination ?? '' },
    { key: 'external_backup', label: 'Optional external-drive folder', type: 'text', default: d.external_backup ?? '' },
    { key: 'backup_retention', label: 'Recent daily copies to keep', type: 'number', default: d.backup_retention ?? 30 },
    { key: 'archive_days', label: 'Long-term archive interval', type: 'select', default: d.archive_days ?? 90, options: [{ value: 60, label: '60 days' }, { value: 90, label: '90 days' }] },
  ];
  return <Panel><FieldForm fields={fields} busy={save.isPending} onSubmit={(v) => save.mutate(v)} error={<><ErrorBox error={save.error} />{save.isSuccess && <div className="success-note">Saved.</div>}</>} /></Panel>;
}

function ApplicationSettings() {
  const data = useQuery({ queryKey: ['settings-app'], queryFn: () => api.get<AppSection[]>('/settings/application') });
  const save = useMutation({ mutationFn: (v: Record<string, any>) => api.put('/settings/application', v) });
  if (!data.data) return <Loading />;
  const fields: FormField[] = data.data.flatMap((s) => s.settings.map((x) => (x.kind === 'bool'
    ? { key: x.key, label: `${s.section} · ${x.label}`, type: 'check' as const, default: Boolean(x.value) }
    : { key: x.key, label: `${s.section} · ${x.label}`, type: 'select' as const, default: x.value, options: x.choices.map((c) => ({ value: c, label: c || 'Use the default' })) })));
  return <Panel><p className="muted">Customer consent and recorded contact details always decide what is actually sent.</p>
    <FieldForm fields={fields} busy={save.isPending} onSubmit={(v) => save.mutate(v)} error={<><ErrorBox error={save.error} />{save.isSuccess && <div className="success-note">Saved.</div>}</>} /></Panel>;
}

function Staff() {
  const client = useQueryClient();
  const rows = useQuery({ queryKey: ['staff'], queryFn: () => api.get<StaffRow[]>('/staff') });
  const [editing, setEditing] = useState<StaffRow | 'new' | null>(null);
  const save = useMutation({
    mutationFn: (v: Record<string, any>) => editing === 'new' ? api.post('/staff', v) : api.put(`/staff/${(editing as StaffRow).id}`, v),
    onSuccess: () => { setEditing(null); client.invalidateQueries({ queryKey: ['staff'] }); },
  });
  const row = editing && editing !== 'new' ? editing : null;
  return (
    <div className="stack">
      <div><button className="primary" onClick={() => setEditing('new')}>+ Staff login</button></div>
      <DataTable rows={rows.data} onOpen={setEditing} columns={[{ key: 'name', label: 'Name' }, { key: 'username', label: 'Username' }, { key: 'role', label: 'Role' },
        { key: 'active', label: 'Active', render: (r) => (r.active ? 'Yes' : 'No') }]} />
      {editing && <Modal title="Staff access" onClose={() => setEditing(null)}>
        <p className="muted">Each person has their own login. Keep at least one active owner.</p>
        <FieldForm compact busy={save.isPending} onSubmit={(v) => save.mutate(v)} error={<ErrorBox error={save.error} />} onCancel={() => setEditing(null)} fields={[
          { key: 'username', label: 'Username', type: 'text', default: row?.username, required: true }, { key: 'name', label: 'Display name', type: 'text', default: row?.name, required: true },
          { key: 'role', label: 'Role', type: 'select', default: row?.role ?? 'counter', options: ['owner', 'counter', 'technician'].map((x) => ({ value: x, label: x })) },
          { key: 'password', label: row ? 'New password (leave blank to keep)' : 'Password (10+ characters)', type: 'text', required: !row },
          { key: 'active', label: 'Active login', type: 'check', default: row ? Boolean(row.active) : true }]} />
      </Modal>}
    </div>
  );
}

function Messaging() {
  const data = useQuery({ queryKey: ['settings-messaging'], queryFn: () => api.get<Record<string, any>>('/settings/messaging') });
  const save = useMutation({
    mutationFn: (v: Record<string, any>) => {
      const templates: Record<string, { name: string; language: string }> = {};
      for (const line of String(v.templates || '').split('\n').filter((l: string) => l.trim())) {
        const [event, name, language] = line.split('|').map((x: string) => x.trim());
        templates[event] = { name, language: language || 'en' };
      }
      return api.put('/settings/messaging', { messaging_mode: v.messaging_mode, notifications_paused: v.notifications_paused, reminder_days: Number(v.reminder_days || 0),
        email_subject: v.email_subject, message_template: v.message_template, templates, whatsapp_token: v.whatsapp_token, smtp_credential: v.smtp_credential,
        whatsapp: { phone_number_id: v.phone_number_id, api_version: v.api_version, photo_template: v.photo_template, photo_language: v.photo_language || 'en' },
        smtp: { host: v.host, port: Number(v.port || 587), username: v.username, from_address: v.from_address, auth: v.auth } });
    },
  });
  if (!data.data) return <Loading />;
  const d = data.data;
  return <Panel>
    <p className="muted">Test mode captures messages locally. Tokens are stored in the operating system credential store, never in the database; leave them blank to keep the stored ones.</p>
    <FieldForm fields={[
      { key: 'messaging_mode', label: 'Sending mode', type: 'select', default: d.messaging_mode, options: [{ value: 'test', label: 'Local test capture (no internet)' }, { value: 'live', label: 'Live providers' }] },
      { key: 'notifications_paused', label: 'Pause outgoing messages', type: 'check', default: d.notifications_paused },
      { key: 'phone_number_id', label: 'WhatsApp phone number ID', type: 'text', default: d.whatsapp.phone_number_id ?? '' },
      { key: 'api_version', label: 'Meta Graph API version', type: 'text', default: d.whatsapp.api_version ?? '' },
      { key: 'whatsapp_token', label: 'New WhatsApp token', type: 'text' },
      { key: 'photo_template', label: 'Approved WhatsApp photo template', type: 'text', default: d.whatsapp.photo_template ?? '' },
      { key: 'photo_language', label: 'Photo template language', type: 'text', default: d.whatsapp.photo_language ?? 'en' },
      { key: 'templates', label: 'Event | approved template | language (one per line)', type: 'textarea',
        default: Object.entries(d.templates ?? {}).map(([e, c]: [string, any]) => `${e} | ${c.name} | ${c.language ?? 'en'}`).join('\n') },
      { key: 'host', label: 'SMTP server', type: 'text', default: d.smtp.host ?? '' }, { key: 'port', label: 'STARTTLS port', type: 'number', default: d.smtp.port ?? 587 },
      { key: 'username', label: 'SMTP account', type: 'text', default: d.smtp.username ?? '' }, { key: 'from_address', label: 'Sender email', type: 'text', default: d.smtp.from_address ?? '' },
      { key: 'auth', label: 'Provider authentication', type: 'select', default: d.smtp.auth ?? 'oauth2', options: [{ value: 'oauth2', label: 'OAuth2 access token' }, { value: 'app_password', label: 'App password' }] },
      { key: 'smtp_credential', label: 'New email token / app password', type: 'text' },
      { key: 'reminder_days', label: 'Collection reminder interval days (0 = off)', type: 'number', default: d.reminder_days },
      { key: 'email_subject', label: 'Email subject template', type: 'text', default: d.email_subject },
      { key: 'message_template', label: 'Message body template · {shop_name} {job_number} {device} {message} {event} {shop_address} {shop_hours}', type: 'textarea', default: d.message_template },
    ]} busy={save.isPending} onSubmit={(v) => save.mutate(v)} error={<><ErrorBox error={save.error} />{save.isSuccess && <div className="success-note">Saved.</div>}</>} />
  </Panel>;
}

function SystemPanel() {
  const health = useQuery({ queryKey: ['health'], queryFn: () => api.get<{ status: string; schema: number; version: string }>('/health') });
  const shutdown = useMutation({ mutationFn: () => api.post('/system/shutdown') });
  return (
    <Panel title="Application">
      <p>Version {health.data?.version ?? '…'} · database schema {health.data?.schema ?? '…'} · status {health.data?.status ?? '…'}</p>
      <p className="muted">RepairShop runs on this computer only. Closing the browser tab leaves it running; use this to close the application.</p>
      {shutdown.isSuccess ? <div className="success-note">The application is closing. You can close this tab.</div>
        : <button className="danger" onClick={() => shutdown.mutate()}>Close RepairShop Manager</button>}
      <ErrorBox error={shutdown.error} />
    </Panel>
  );
}
