import { createContext, ReactNode, useContext } from 'react';
import type { Me } from '../api/types';

const SessionContext = createContext<Me | null>(null);

export function SessionProvider({ me, children }: { me: Me; children: ReactNode }) {
  return <SessionContext.Provider value={me}>{children}</SessionContext.Provider>;
}

export function useMe(): Me {
  const me = useContext(SessionContext);
  if (!me) throw new Error('useMe outside a signed-in session');
  return me;
}

/**
 * Whether to OFFER a control. Hiding a button is only tidiness: every endpoint enforces
 * the same permission again on the server, so this is never a security check.
 */
export function useCan() {
  const me = useMe();
  return (permission: string) => me.permissions.includes(permission);
}
