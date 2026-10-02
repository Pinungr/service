import { FormEvent, ReactNode, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, ApiError } from '../../api/client';
import type { AuthStatus, Me } from '../../api/types';
import { SessionProvider } from '../../app/session';
import { ErrorBox, Loading } from '../../components/ui';
import { setShopTimezone } from '../../shared/dates';

/** Shows first-run setup or sign-in until the server confirms a session. */
export function AuthGate({ children }: { children: ReactNode }) {
  const me = useQuery({
    queryKey: ['me'],
    queryFn: async () => {
      try {
        return await api.get<Me>('/auth/me');
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) return null;
        throw error;
      }
    },
    staleTime: 60_000,
  });
  const status = useQuery({ queryKey: ['auth-status'], queryFn: () => api.get<AuthStatus>('/auth/status'), enabled: me.data === null });
  if (me.isLoading) return <div className="center"><Loading label="Opening RepairShop…" /></div>;
  if (me.error) return <div className="login panel"><ErrorBox error={me.error} /></div>;
  if (me.data) {
    setShopTimezone(me.data.timezone);
    return <SessionProvider me={me.data}>{children}</SessionProvider>;
  }
  if (!status.data) return <div className="center"><Loading /></div>;
  return status.data.setup_required ? <Setup /> : <Login shop={status.data.shop_name} />;
}

function Login({ shop }: { shop: string }) {
  const client = useQueryClient();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const login = useMutation({
    mutationFn: () => api.post<Me>('/auth/login', { username, password }),
    onSuccess: (me) => { client.setQueryData(['me'], me); client.invalidateQueries(); },
  });
  const submit = (event: FormEvent) => { event.preventDefault(); login.mutate(); };
  return (
    <form className="login panel form" onSubmit={submit}>
      <div>
        <h1>RepairShop</h1>
        <p className="muted">{shop || 'Your shop'} · sign in to continue</p>
      </div>
      <label className="field"><span className="label">Username</span>
        <input autoFocus autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} />
      </label>
      <label className="field"><span className="label">Password</span>
        <input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
      </label>
      <ErrorBox error={login.error} />
      <button className="primary" disabled={login.isPending || !username || !password}>{login.isPending ? 'Signing in…' : 'Sign in'}</button>
    </form>
  );
}

function Setup() {
  const client = useQueryClient();
  const [values, setValues] = useState({ shop: '', name: '', username: '', password: '' });
  const setup = useMutation({
    mutationFn: () => api.post<Me>('/auth/setup', values),
    onSuccess: (me) => { client.setQueryData(['me'], me); client.invalidateQueries(); },
  });
  const field = (key: keyof typeof values, label: string, type = 'text') => (
    <label className="field"><span className="label required">{label}</span>
      <input type={type} value={values[key]} onChange={(e) => setValues({ ...values, [key]: e.target.value })} />
    </label>
  );
  return (
    <form className="login panel form" onSubmit={(e) => { e.preventDefault(); setup.mutate(); }}>
      <div>
        <h1>Welcome to RepairShop</h1>
        <p className="muted">Set up this shop and create its owner login. Data stays on this computer; no internet is required.</p>
      </div>
      {field('shop', 'Shop name')}
      {field('name', "Owner's name")}
      {field('username', 'Owner username')}
      {field('password', 'Password (at least 10 characters)', 'password')}
      <ErrorBox error={setup.error} />
      <button className="primary" disabled={setup.isPending}>Create shop</button>
    </form>
  );
}
