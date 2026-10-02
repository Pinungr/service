import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter } from 'react-router-dom';
import { ApiError } from './api/client';
import { App } from './app/App';
import './styles.css';

const client = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 10_000,
      refetchOnWindowFocus: true,
      retry: (count, error) => !(error instanceof ApiError && error.status > 0 && error.status < 500) && count < 2,
    },
  },
});

// A session that ended on the server (sign-out elsewhere, restart, deactivated login)
// sends the user back to sign-in instead of showing a broken page.
client.getQueryCache().subscribe((event) => {
  const error = event.type === 'updated' ? event.query.state.error : null;
  if (error instanceof ApiError && error.status === 401 && event.query.queryKey[0] !== 'me') client.setQueryData(['me'], null);
});
client.getMutationCache().subscribe((event) => {
  const error = event.mutation?.state.error;
  if (error instanceof ApiError && error.status === 401) client.setQueryData(['me'], null);
});

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={client}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
