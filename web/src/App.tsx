import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { lazy, Suspense, useState, type ReactNode } from 'react'
import { createBrowserRouter, createMemoryRouter, RouterProvider, type RouteObject } from 'react-router'
import { ApiError } from './api/client'
import { AppShell } from './components/layout/AppShell'
import { LoadingBlock } from './components/ui/States'
import { NotFoundPage } from './pages/NotFoundPage'

const OverviewPage = lazy(() => import('./pages/OverviewPage'))
const LineupsPage = lazy(() => import('./pages/LineupsPage'))
const LineupDetailPage = lazy(() => import('./pages/LineupDetailPage'))
const PredictPage = lazy(() => import('./pages/PredictPage'))
const InsightsPage = lazy(() => import('./pages/InsightsPage'))
const ModelPage = lazy(() => import('./pages/ModelPage'))

const page = (el: ReactNode) => <Suspense fallback={<LoadingBlock label="Loading page" />}>{el}</Suspense>

export const routes: RouteObject[] = [
  {
    path: '/',
    element: <AppShell />,
    children: [
      { index: true, element: page(<OverviewPage />) },
      { path: 'lineups', element: page(<LineupsPage />) },
      { path: 'lineups/:lineupId', element: page(<LineupDetailPage />) },
      { path: 'predict', element: page(<PredictPage />) },
      { path: 'insights', element: page(<InsightsPage />) },
      { path: 'model', element: page(<ModelPage />) },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
]

export function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // Retry only transient failures (network, 503, 504); a 4xx will not fix itself.
        retry: (count, error) => count < 2 && error instanceof ApiError && error.transient,
        refetchOnWindowFocus: false,
      },
    },
  })
}

export function App({ client, initialEntries }: { client?: QueryClient; initialEntries?: string[] }) {
  const [queryClient] = useState(() => client ?? makeQueryClient())
  const [router] = useState(() => (initialEntries ? createMemoryRouter(routes, { initialEntries }) : createBrowserRouter(routes)))
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  )
}
