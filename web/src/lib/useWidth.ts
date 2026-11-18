import { useEffect, useRef, useState } from 'react'

/** Width of an element, kept current with a ResizeObserver (for hand-drawn SVG charts). */
export function useWidth<T extends HTMLElement>(fallback = 320) {
  const ref = useRef<T>(null)
  const [width, setWidth] = useState(fallback)
  useEffect(() => {
    const el = ref.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(([entry]) => {
      const w = Math.round(entry.contentRect.width)
      if (w > 0) setWidth(w)
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return { ref, width }
}
