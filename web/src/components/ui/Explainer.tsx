import type { ReactNode } from 'react'

/** A collapsible explanation: the summary is always visible, the detail opens on demand. */
export function Explainer({ title, children, testId }: { title: string; children: ReactNode; testId?: string }) {
  return (
    <details className="group rounded-lg border border-line bg-surface open:bg-surface" data-testid={testId}>
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 text-sm font-medium text-ink hover:bg-surface-2 [&::-webkit-details-marker]:hidden">
        {title}
        <svg viewBox="0 0 20 20" className="size-4 shrink-0 text-muted transition-transform group-open:rotate-180" fill="currentColor" aria-hidden>
          <path d="M5.2 7.5 10 12.3l4.8-4.8 1.1 1.1-5.9 5.9-5.9-5.9z" />
        </svg>
      </summary>
      <div className="space-y-2 border-t border-line px-4 py-3 text-sm leading-relaxed text-ink-2">{children}</div>
    </details>
  )
}
