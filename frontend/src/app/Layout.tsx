import { KeyboardEvent, ReactNode, useEffect, useState } from 'react';
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, qs } from '../api/client';
import { useCan, useMe } from './session';

interface NavItem { to: string; label: string; permission?: string; group?: string }

// Same screens and permissions as the desktop navigation. Hiding is tidiness only.
const NAV: NavItem[] = [
  { to: '/dashboard', label: 'Dashboard', group: 'WORKSHOP' },
  { to: '/intake', label: 'New Repair Intake', permission: 'intake' },
  { to: '/repairs', label: 'Active Repairs' },
  { to: '/repairs?filter=ready', label: 'Ready for Delivery', permission: 'customer_delivery' },
  { to: '/repairs?filter=history', label: 'Repair History', permission: 'view_all_jobs' },
  { to: '/inventory', label: 'Inventory', permission: 'inventory' },
  { to: '/customers', label: 'Customers', permission: 'customer_records', group: 'PEOPLE & SALES' },
  { to: '/sales', label: 'Products sold', permission: 'register_sale' },
  { to: '/dispatch', label: 'Dispatch & receive', permission: 'handover' },
  { to: '/contacts', label: 'Contacts & Services', permission: 'directories' },
  { to: '/quotes', label: 'Quotations', permission: 'create_quote', group: 'ACCOUNTS' },
  { to: '/accounts/customer', label: 'Customer accounts', permission: 'collect_payment' },
  { to: '/accounts/vendor', label: 'Vendor accounts', permission: 'vendor_accounts' },
  { to: '/reports', label: 'Reports', permission: 'reports' },
  { to: '/notifications', label: 'Notifications', permission: 'messaging', group: 'MANAGEMENT' },
  { to: '/backups', label: 'Backups', permission: 'backup_restore' },
  { to: '/settings', label: 'Settings & staff', permission: 'settings' },
];

export function Layout() {
  const me = useMe();
  const can = useCan();
  const location = useLocation();
  const client = useQueryClient();
  const logout = useMutation({ mutationFn: () => api.post('/auth/logout'), onSuccess: () => client.setQueryData(['me'], null) });
  const isActive = (to: string) => {
    const [path, query] = to.split('?');
    if (query) return location.pathname === path && location.search === '?' + query;
    return location.pathname.startsWith(path) && !(path === '/repairs' && /filter=(ready|history)/.test(location.search));
  };
  return (
    <div className="shell">
      <nav className="sidebar" aria-label="Main navigation">
        <div className="brand">RepairShop</div>
        <div className="brand-sub">SERVICE &amp; REPAIR MANAGER</div>
        <div className="nav">
          {NAV.filter((item) => !item.permission || can(item.permission)).map((item) => (
            <div key={item.to}>
              {item.group && <div className="nav-group">{item.group}</div>}
              <NavLink to={item.to} className={() => (isActive(item.to) ? 'active' : '')}>{item.label}</NavLink>
            </div>
          ))}
        </div>
        <div className="sidebar-foot">
          <span>{me.name} · {me.role}</span>
          <button onClick={() => logout.mutate()}>Sign out</button>
        </div>
      </nav>
      <main className="main">
        <div className="topbar">
          <GlobalSearch />
          <div className="shop-badge">{me.shop_name || 'Your shop'}</div>
        </div>
        <Outlet />
      </main>
    </div>
  );
}

interface Hit { id: number; number: string; customer: string; phone: string; device: string; status: string }

function GlobalSearch() {
  const navigate = useNavigate();
  const [text, setText] = useState('');
  const [term, setTerm] = useState('');
  const [focus, setFocus] = useState(0);
  useEffect(() => { const t = setTimeout(() => setTerm(text.trim()), 200); return () => clearTimeout(t); }, [text]);
  const hits = useQuery({ queryKey: ['search', term], queryFn: () => api.get<Hit[]>('/search' + qs({ q: term })), enabled: term.length > 1 });
  const open = (hit: Hit) => { setText(''); setTerm(''); navigate('/repairs/' + hit.id); };
  const onKey = (event: KeyboardEvent<HTMLInputElement>) => {
    const rows = hits.data ?? [];
    if (event.key === 'ArrowDown') { setFocus((f) => Math.min(rows.length - 1, f + 1)); event.preventDefault(); }
    if (event.key === 'ArrowUp') { setFocus((f) => Math.max(0, f - 1)); event.preventDefault(); }
    if (event.key === 'Escape') { setText(''); setTerm(''); }
    if (event.key === 'Enter' && rows.length) {
      const exact = rows.find((r) => r.number.toLowerCase() === text.trim().toLowerCase());
      open(exact ?? rows[Math.min(focus, rows.length - 1)]);
    }
  };
  return (
    <div style={{ position: 'relative', flex: '1 1 auto', maxWidth: 640 }}>
      <input aria-label="Global job search" placeholder="Search mobile number, REP- job number, DEV- product ID or customer…"
             value={text} onChange={(e) => { setText(e.target.value); setFocus(0); }} onKeyDown={onKey} />
      {term.length > 1 && hits.data && (
        <div className="search-results" role="listbox">
          {hits.data.length === 0 && <div className="hit muted">No matching jobs</div>}
          {hits.data.map((hit, index) => (
            <div key={hit.id} role="option" aria-selected={index === focus} className={'hit' + (index === focus ? ' focused' : '')}
                 onMouseDown={() => open(hit)}>
              <strong>{hit.number}</strong> · {hit.customer} · {hit.phone}
              <div className="small muted">{hit.device} · {hit.status}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function PageTitle({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  useEffect(() => { document.title = title + ' · RepairShop'; }, [title]);
  return (
    <div className="row between" style={{ marginBottom: 14 }}>
      <div>
        <h1>{title}</h1>
        {subtitle && <div className="muted" style={{ marginTop: 4 }}>{subtitle}</div>}
      </div>
      {actions && <div className="row">{actions}</div>}
    </div>
  );
}
