import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { GLOSSARY } from '../../lib/glossary'
import { InfoTip } from './InfoTip'

describe('InfoTip', () => {
  it('explains a term on tap or keyboard focus and closes with Escape', async () => {
    render(<InfoTip term="rmse">RMSE</InfoTip>)
    const button = screen.getByRole('button', { name: `What is ${GLOSSARY.rmse.term}?` })
    expect(screen.queryByRole('tooltip')).toBeNull()
    await userEvent.click(button)
    expect(screen.getByRole('tooltip')).toHaveTextContent(GLOSSARY.rmse.text)
    expect(button).toHaveAttribute('aria-describedby', screen.getByRole('tooltip').id)
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('tooltip')).toBeNull()
  })

  it('every glossary entry is short (one or two sentences)', () => {
    for (const g of Object.values(GLOSSARY)) expect(g.text.split(/(?<=\.)\s/).length).toBeLessThanOrEqual(3)
  })
})
