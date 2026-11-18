import { render } from '@testing-library/react'
import { App, makeQueryClient } from '../App'

/** Render the whole app (real routes, real components) at a URL, against the MSW fixture server. */
export function renderApp(path: string) {
  const client = makeQueryClient()
  client.setDefaultOptions({ queries: { ...client.getDefaultOptions().queries, retry: false } })
  return render(<App client={client} initialEntries={[path]} />)
}
