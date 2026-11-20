import clsx from 'clsx'
import { useId, type ButtonHTMLAttributes, type ReactNode, type SelectHTMLAttributes } from 'react'

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'ghost'
  size?: 'sm' | 'md'
}

export function Button({ variant = 'primary', size = 'md', className, ...rest }: ButtonProps) {
  return (
    <button
      type="button"
      {...rest}
      className={clsx(
        'inline-flex items-center justify-center gap-1.5 rounded-md font-medium whitespace-nowrap transition-colors disabled:cursor-not-allowed disabled:opacity-50',
        size === 'sm' ? 'h-8 px-3 text-sm' : 'h-10 px-4 text-sm',
        variant === 'primary' && 'bg-accent text-accent-ink hover:brightness-110',
        variant === 'secondary' && 'border border-line-strong bg-surface text-ink hover:bg-surface-2',
        variant === 'ghost' && 'text-ink-2 hover:bg-surface-2 hover:text-ink',
        className,
      )}
    />
  )
}

export function Field({ label, children, hint, className }: { label: string; children: (id: string) => ReactNode; hint?: string; className?: string }) {
  const id = useId()
  return (
    <div className={clsx('flex min-w-0 flex-col gap-1', className)}>
      <label htmlFor={id} className="text-xs font-medium tracking-wide text-muted uppercase">
        {label}
      </label>
      {children(id)}
      {hint && <p className="text-xs text-muted">{hint}</p>}
    </div>
  )
}

const controlClass =
  'h-10 w-full min-w-0 rounded-md border border-line-strong bg-surface px-3 text-sm text-ink shadow-xs focus:border-accent focus:outline-none disabled:opacity-50'

export function Select({ className, leading, ...rest }: SelectHTMLAttributes<HTMLSelectElement> & { leading?: ReactNode }) {
  return (
    <div className="relative">
      {leading && <span className="pointer-events-none absolute top-1/2 left-2.5 flex -translate-y-1/2 items-center">{leading}</span>}
      <select {...rest} className={clsx(controlClass, 'appearance-none pr-9', leading && 'pl-9', className)} />
      <svg aria-hidden viewBox="0 0 20 20" className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-muted" fill="currentColor">
        <path d="M5.2 7.5 10 12.3l4.8-4.8 1.1 1.1-5.9 5.9-5.9-5.9z" />
      </svg>
    </div>
  )
}

export function TextInput({ className, ...rest }: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...rest} className={clsx(controlClass, className)} />
}

/** A labelled select bound to a value; `options` carry their own display text. */
export function SelectField<T extends string | number>({
  label,
  value,
  options,
  onChange,
  hint,
  className,
  disabled,
  leading,
}: {
  label: string
  value: T
  options: { value: T; label: string }[]
  onChange: (v: T) => void
  hint?: string
  className?: string
  disabled?: boolean
  /** Shown inside the control, before the text (e.g. the selected team's logo). */
  leading?: ReactNode
}) {
  return (
    <Field label={label} hint={hint} className={className}>
      {(id) => (
        <Select
          id={id}
          value={String(value)}
          disabled={disabled}
          leading={leading}
          onChange={(e) => {
            const raw = e.target.value
            const match = options.find((o) => String(o.value) === raw)
            if (match) onChange(match.value)
          }}
        >
          {options.map((o) => (
            <option key={String(o.value)} value={String(o.value)}>
              {o.label}
            </option>
          ))}
        </Select>
      )}
    </Field>
  )
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
  size = 'md',
}: {
  value: T
  options: { value: NoInfer<T>; label: string }[]
  onChange: (v: NoInfer<T>) => void
  label: string
  size?: 'sm' | 'md'
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex max-w-full overflow-x-auto rounded-md border border-line-strong bg-surface-2 p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={o.value === value}
          onClick={() => onChange(o.value)}
          className={clsx(
            'rounded-[5px] font-medium whitespace-nowrap transition-colors',
            size === 'sm' ? 'px-2.5 py-1 text-xs' : 'px-3 py-1.5 text-sm',
            o.value === value ? 'bg-surface text-ink shadow-sm' : 'text-ink-2 hover:text-ink',
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

export function Switch({ checked, onChange, label, description }: { checked: boolean; onChange: (v: boolean) => void; label: string; description?: string }) {
  const id = useId()
  return (
    <div className="flex items-start gap-3">
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={clsx(
          'relative mt-0.5 inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors',
          checked ? 'bg-accent' : 'bg-surface-3 ring-1 ring-line-strong',
        )}
      >
        <span className={clsx('inline-block size-4 rounded-full bg-white shadow transition-transform', checked ? 'translate-x-4.5' : 'translate-x-0.5')} />
      </button>
      <label htmlFor={id} className="cursor-pointer text-sm">
        <span className="font-medium text-ink">{label}</span>
        {description && <span className="block text-xs text-muted">{description}</span>}
      </label>
    </div>
  )
}

/** Possession threshold presets, shared by every filter bar. */
export const POSS_PRESETS = [0, 25, 50, 100, 200, 300, 500]

export function PossessionSelect({
  label,
  value,
  onChange,
  presets = POSS_PRESETS,
  hint,
}: {
  label: string
  value: number
  onChange: (v: number) => void
  presets?: number[]
  hint?: string
}) {
  const options = (presets.includes(value) ? presets : [...presets, value].sort((a, b) => a - b)).map((p) => ({
    value: p,
    label: p === 0 ? 'Any' : `≥ ${p}`,
  }))
  return <SelectField label={label} value={value} options={options} onChange={onChange} hint={hint} />
}
