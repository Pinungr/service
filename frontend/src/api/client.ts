// The only way the browser talks to the backend: same-origin JSON over /api.
// No database, path or credential ever reaches this code; the backend decides everything.

export interface ErrorBody {
  code: string;
  message: string;
  field?: string | null;
  refresh?: boolean;
  matches?: DuplicateMatch[];
}

export interface DuplicateMatch {
  id: number;
  name: string;
  secondary: string;
  reasons: string[];
  exact: boolean;
  active: boolean;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly field: string | null;
  readonly body: ErrorBody;

  constructor(status: number, body: ErrorBody) {
    super(body.message);
    this.status = status;
    this.code = body.code;
    this.field = body.field ?? null;
    this.body = body;
  }

  /** The record changed or the step is no longer available: reload before trying again. */
  get needsRefresh(): boolean {
    return this.status === 409 && Boolean(this.body.refresh);
  }
}

const HEADERS = { 'X-Requested-With': 'RepairShop' };

type Method = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';

async function request<T>(method: Method, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, credentials: 'same-origin', headers: { ...HEADERS } };
  if (body instanceof FormData) {
    init.body = body;
  } else if (body !== undefined) {
    init.body = JSON.stringify(body);
    (init.headers as Record<string, string>)['Content-Type'] = 'application/json';
  }
  let response: Response;
  try {
    response = await fetch('/api' + path, init);
  } catch {
    throw new ApiError(0, { code: 'OFFLINE', message: 'The RepairShop server is not responding. Check that the application is running.' });
  }
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  const data = text ? safeJson(text) : undefined;
  if (!response.ok) {
    const error = (data as { error?: ErrorBody } | undefined)?.error;
    throw new ApiError(response.status, error ?? { code: 'HTTP_ERROR', message: 'The request failed (' + response.status + ').' });
  }
  return data as T;
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return undefined;
  }
}

export const api = {
  get: <T>(path: string) => request<T>('GET', path),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body ?? {}),
  put: <T>(path: string, body?: unknown) => request<T>('PUT', path, body ?? {}),
  patch: <T>(path: string, body?: unknown) => request<T>('PATCH', path, body ?? {}),
  upload: <T>(path: string, form: FormData) => request<T>('POST', path, form),
};

/** Query string from defined values only. */
export function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const parts = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null && v !== '')
    .map(([k, v]) => encodeURIComponent(k) + '=' + encodeURIComponent(String(v)));
  return parts.length ? '?' + parts.join('&') : '';
}

/** A fresh idempotency key: a retried request with the same key is applied once. */
export function operationId(): string {
  return (globalThis.crypto?.randomUUID?.() ?? Math.random().toString(36).slice(2) + Date.now().toString(36)).replace(/-/g, '');
}

export function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : 'Something went wrong.';
}
