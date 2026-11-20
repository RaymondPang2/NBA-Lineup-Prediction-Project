import { useSyncExternalStore } from 'react'
import type { LogoVariant } from './teamLogo'

function subscribe(cb: () => void) {
  const mq = window.matchMedia?.('(prefers-color-scheme: dark)')
  mq?.addEventListener?.('change', cb)
  const mo = new MutationObserver(cb)
  mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
  return () => {
    mq?.removeEventListener?.('change', cb)
    mo.disconnect()
  }
}

function snapshot(): LogoVariant {
  const t = document.documentElement.getAttribute('data-theme')
  if (t === 'light' || t === 'dark') return t
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

/** The theme actually on screen: the viewer's choice (html[data-theme]) or else the OS preference. */
export function useResolvedTheme(): LogoVariant {
  return useSyncExternalStore(subscribe, snapshot, () => 'light')
}
