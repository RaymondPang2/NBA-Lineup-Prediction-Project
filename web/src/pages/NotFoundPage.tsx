import { Link } from 'react-router'
import { EmptyState } from '../components/ui/States'

export function NotFoundPage() {
  return (
    <EmptyState
      title="Page not found"
      action={
        <Link to="/" className="text-sm font-medium text-accent hover:underline">
          Back to the overview
        </Link>
      }
    >
      There is no page at this address.
    </EmptyState>
  )
}
