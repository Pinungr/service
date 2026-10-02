// Response shapes of the backend API. Money fields are whole paise.

export interface Me {
  id: number;
  username: string;
  name: string;
  role: 'owner' | 'counter' | 'technician';
  permissions: string[];
  shop_name: string;
  timezone: string;
  messaging_mode: string;
}

export interface AuthStatus {
  setup_required: boolean;
  shop_name: string;
  authenticated: boolean;
}

export interface Page<T> {
  items: T[];
  offset: number;
  limit: number;
  has_more: boolean;
}

export interface Option<V = string | number> {
  value: V;
  label: string;
  disabled?: boolean;
  reason?: string;
  type?: string;
  expected?: number;
}

export interface RepairSummary {
  id: number;
  number: string;
  visit: string | null;
  customer: string;
  phone: string;
  device: string;
  device_id: number | null;
  route: string;
  status: string;
  location: string;
  responsible: string;
  current_custodian: string;
  stage_age: string;
  expected_date: string | null;
  balance: number;
  estimate: number;
  next_action: string;
  attention: string;
}

export interface ActionRef {
  key: string;
  label: string;
  group: 'step' | 'tool' | 'exception';
  primary: boolean;
}

export interface Assignment {
  id: number | null;
  route: string | null;
  contact_id: number | null;
  party: string | null;
  contact: string | null;
  summary: string | null;
  partner: Record<string, unknown>;
  reference: string | null;
  expected_return: string | null;
  instructions: string | null;
  technician: string | null;
}

export interface Custodian {
  name: string;
  kind: string;
  role: string;
  location: string;
}

export interface RepairDetail {
  id: number;
  number: string;
  version: number;
  stage: string;
  stage_label: string;
  route: string;
  route_label: string;
  current_status: string;
  customer_id: number;
  customer: string;
  phone: string;
  device: string;
  device_id: number | null;
  serial: string;
  complaint: string;
  damage: string;
  customer_requirement: string;
  received: string;
  received_by: string;
  visit_number: string | null;
  warranty_status: string;
  responsible: string;
  assigned_technician: string;
  current_custodian: string;
  custodian_role: string;
  custodian_since: string | null;
  custodians: Custodian[];
  current_location: string;
  final_destination: string;
  at_shop: boolean;
  away: boolean;
  next_action: string;
  primary: string;
  actions: ActionRef[];
  attention: string[];
  assignment: Assignment;
  quote: { id?: number; version?: number; state?: string; total?: number; valid_until?: string | null; scope?: string };
  balance: number;
  paid: number;
  initial_estimate: number;
  deposit: number;
  repair_due: string | null;
  collection_due: string | null;
  return_due: string | null;
  hold_reason: string;
  legacy: boolean;
  current_card: string;
  warranty_indicator: string;
  open_claims: number;
  record: Record<string, any>;
  vendor_payments: boolean;
}

export type NodeStatus = 'completed' | 'current' | 'waiting' | 'future' | 'failed' | 'cancelled' | 'skipped';

export interface JourneyNode {
  key: string;
  label: string;
  status: NodeStatus;
  detail: string;
  current: boolean;
  options: string[];
  events: { created: string | null; actor: string | null; details: string | null }[];
  action: ActionRef | null;
}

export interface Journey {
  repair_id: number;
  job_number: string;
  version: number;
  current_stage: string;
  route: string;
  route_label: string;
  next_action: string;
  nodes: JourneyNode[];
}

export type FieldType =
  | 'text' | 'textarea' | 'date' | 'time' | 'money' | 'number' | 'select' | 'check' | 'info'
  | 'contact' | 'transport' | 'items' | 'return_items' | 'route';

export interface FormField {
  key: string;
  label: string;
  type: FieldType;
  required?: boolean;
  default?: any;
  options?: Option<any>[];
  discrepancies?: Option<string>[];
  kind?: string;
  job_id?: number;
  show_if?: { field: string; equals: unknown[] };
  placeholder?: string;
  help?: string;
}

export interface ActionForm {
  action: string;
  title: string;
  description: string;
  fields: FormField[];
  submit_label: string;
  confirm: string | null;
  navigate: string | null;
  version: number;
}

export interface ActionResult {
  replayed: boolean;
  repair: RepairDetail;
}

export interface ContactOption {
  id: number;
  name: string;
  secondary: string;
  headline: string;
  summary: string;
  recommended: boolean;
  reasons: string[];
  snapshot: Record<string, any>;
}

export interface ContactOptions {
  recommended: ContactOption[];
  others: ContactOption[];
}

export interface ContactSummary {
  id: number;
  kind: string;
  name: string;
  mobile: string;
  contact_person: string;
  location: string;
  works_on: string;
  route_from: string;
  route_to: string;
  pickup_point: string;
  drop_point: string;
  vehicle_number: string;
  active: boolean;
  status: string;
}

export interface ContactDetail extends ContactSummary {
  kind_label: string;
  alternate: string;
  email: string;
  address_line1: string;
  address_line2: string;
  city: string;
  district: string;
  state: string;
  pincode: string;
  specialization: string;
  notes: string;
  warranty_service: boolean;
  pickup: boolean;
  turnaround_days: number;
  photo_id: number | null;
  supports: number[];
  brands: string[];
  summary: string;
  activity: Record<string, number | null>;
}

export interface StoredFile {
  id: number;
  title: string;
  kind: string;
  job_id: number | null;
  created: string | null;
  url: string;
}

export interface TransportMethod {
  key: 'BUS' | 'COURIER' | 'IN_HAND';
  label: string;
  uses_bus_service: boolean;
  free_text_company: boolean;
  fields: { key: string; label: string; type: 'text' | 'date' | 'time'; required: boolean }[];
}

export interface Dispatch {
  id: number;
  version: number;
  current: boolean;
  status: string;
  party: string | null;
  contact_snapshot: Record<string, any>;
  transporter: string;
  transporter_snapshot: Record<string, any>;
  reference: string;
  transport_mode: string;
  transport: Record<string, string>;
  transport_summary: string;
  carrier: string;
  amount: number;
  paid_by: string;
  expected_return: string | null;
  condition: string;
  notes: string;
  manifest: number[];
  actual_dispatch_at: string | null;
  amendment_reason: string;
  editable: boolean;
  created: string;
}

export interface Attempt {
  attempt: number;
  partner: string | null;
  snapshot: Record<string, any>;
  route: string;
  reference: string;
  expected_return: string | null;
  assigned: string;
  sent: string | null;
  returned: string | null;
  result: string;
  current: boolean;
}

export interface CustomerSummary {
  id: number;
  name: string;
  phone: string;
  email: string;
  address: string;
}
