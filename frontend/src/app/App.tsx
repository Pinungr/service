import { Navigate, Route, Routes } from 'react-router-dom';
import { AuthGate } from '../features/auth/AuthGate';
import { Layout } from './Layout';
import { DashboardPage } from '../features/dashboard/DashboardPage';
import { RepairsPage } from '../features/repairs/RepairsPage';
import { RepairWorkspace } from '../features/repairs/RepairWorkspace';
import { IntakePage } from '../features/intake/IntakePage';
import { CustomerPage, CustomersPage } from '../features/customers/CustomersPage';
import { ContactsPage } from '../features/contacts/ContactsPage';
import { DispatchPage } from '../features/dispatch/DispatchPage';
import { InventoryPage } from '../features/inventory/InventoryPage';
import { QuotesPage } from '../features/billing/QuotesPage';
import { AccountsPage } from '../features/billing/AccountsPage';
import { SalesPage } from '../features/billing/SalesPage';
import { ReportsPage } from '../features/reports/ReportsPage';
import { SettingsPage } from '../features/settings/SettingsPage';
import { NotificationsPage } from '../features/settings/NotificationsPage';
import { BackupsPage } from '../features/settings/BackupsPage';

export function App() {
  return (
    <AuthGate>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/intake" element={<IntakePage />} />
          <Route path="/repairs" element={<RepairsPage />} />
          <Route path="/repairs/:repairId" element={<RepairWorkspace />} />
          <Route path="/customers" element={<CustomersPage />} />
          <Route path="/customers/:customerId" element={<CustomerPage />} />
          <Route path="/contacts" element={<ContactsPage />} />
          <Route path="/dispatch" element={<DispatchPage />} />
          <Route path="/inventory" element={<InventoryPage />} />
          <Route path="/quotes" element={<QuotesPage />} />
          <Route path="/accounts/:accountType" element={<AccountsPage />} />
          <Route path="/accounts" element={<Navigate to="/accounts/customer" replace />} />
          <Route path="/sales" element={<SalesPage />} />
          <Route path="/reports" element={<ReportsPage />} />
          <Route path="/notifications" element={<NotificationsPage />} />
          <Route path="/backups" element={<BackupsPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<div className="panel">This page does not exist. Use the menu on the left.</div>} />
        </Route>
      </Routes>
    </AuthGate>
  );
}
