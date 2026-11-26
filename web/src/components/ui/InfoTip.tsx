import clsx from 'clsx'
import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { GLOSSARY, type GlossaryKey } from '../../lib/glossary'

/**
 * A small "i" button that explains a term. Works with mouse (hover), keyboard (focus, Escape) and touch (tap);
 * the definition is linked to the button for screen readers. Definitions live in lib/glossary.ts.
 */
export function InfoTip({ term, children, className }: { term: GlossaryKey; children?: ReactNode; className?: string }) {
  const g = GLOSSARY[term]
  const [open, setOpen] = useState(false)
  const id = useId()
  const box = useRef<HTMLSpanElement>(null)

  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent) => box.current && !box.current.contains(e.target as Node) && setOpen(false)
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', esc)
    return () => {
      document.removeEventListener('mousedown', close)
      document.removeEventListener('keydown', esc)
    }
  }, [open])

  return (
    <span ref={box} className={clsx('relative inline-flex items-center gap-1 normal-case', className)} onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}>
      {children}
      <button
        type="button"
        aria-label={`What is ${g.term}?`}
        aria-describedby={open ? id : undefined}
        aria-expanded={open}
        onClick={(e) => {
          e.stopPropagation()
          setOpen(true) // hover or focus may already have opened it; a click never closes it by surprise
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        className="inline-flex size-4 shrink-0 items-center justify-center rounded-full text-muted hover:text-accent focus-visible:text-accent focus-visible:outline-2 focus-visible:outline-accent"
      >
        <svg viewBox="0 0 16 16" className="size-3.5" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden>
          <circle cx="8" cy="8" r="6.5" />
          <path d="M8 7.2v4M8 4.8v.1" strokeLinecap="round" />
        </svg>
      </button>
      {open && (
        <span
          id={id}
          role="tooltip"
          className="absolute top-full left-1/2 z-50 mt-1.5 w-64 -translate-x-1/2 rounded-lg border border-line-strong bg-surface p-3 text-left text-xs leading-relaxed font-normal tracking-normal whitespace-normal text-ink-2 shadow-lg"
        >
          <span className="mb-0.5 block font-semibold text-ink">{g.term}</span>
          {g.text}
        </span>
      )}
    </span>
  )
}
