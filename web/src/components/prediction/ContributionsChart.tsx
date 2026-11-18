import { Bar, BarChart, Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { Contribution } from '../../api/types'
import { axisTicks } from '../../lib/axis'
import { featureLabel } from '../../lib/features'
import { useWidth } from '../../lib/useWidth'
import { fmtNum, fmtSigned } from '../../lib/format'
import { C, TooltipBox } from '../charts/ChartFrame'
import { TableWrap, Td, Th } from '../ui/Table'

/**
 * How each feature moves this prediction away from the intercept (a training-average lineup):
 * contribution = standardized coefficient × (value − training mean) / training SD. Sorted by size.
 */
export function ContributionsChart({ contributions }: { contributions: Contribution[] }) {
  const data = [...contributions]
    .sort((a, b) => Math.abs(b.contribution) - Math.abs(a.contribution))
    .map((c) => ({ ...c, label: featureLabel(c.feature) }))
  const max = Math.max(1, ...data.map((d) => Math.abs(d.contribution)))
  const lim = Math.ceil(max)
  const { ref, width } = useWidth<HTMLDivElement>()
  const narrow = width < 520
  return (
    <div ref={ref} className="min-w-0" style={{ height: 36 + data.length * 30 }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 16, bottom: 4, left: 4 }} barCategoryGap={6}>
          <XAxis type="number" domain={[-lim, lim]} ticks={axisTicks(lim, narrow)} tickFormatter={(v: number) => fmtSigned(v, 0)} tickLine={false} />
          <YAxis type="category" dataKey="label" width={narrow ? 128 : 200} tickLine={false} axisLine={false} interval={0} tick={{ fontSize: narrow ? 11 : 12 }} />
          <ReferenceLine x={0} stroke={C.axis} />
          <Tooltip
            cursor={{ fill: 'var(--surface-2)' }}
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null
              const d = payload[0].payload as Contribution & { label: string }
              return (
                <TooltipBox
                  title={d.label}
                  rows={[
                    { label: 'Contribution', value: fmtSigned(d.contribution, 2) },
                    { label: 'Feature value', value: fmtNum(d.value, 2) },
                  ]}
                />
              )
            }}
          />
          <Bar dataKey="contribution" radius={4} isAnimationActive={false}>
            {data.map((d) => (
              <Cell key={d.feature} fill={d.contribution >= 0 ? C.pos : C.neg} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

export function ContributionsTable({ contributions }: { contributions: Contribution[] }) {
  return (
    <TableWrap label="Feature contributions">
      <thead>
        <tr>
          <Th align="left">Feature</Th>
          <Th>Value</Th>
          <Th>Contribution</Th>
        </tr>
      </thead>
      <tbody>
        {[...contributions]
          .sort((a, b) => Math.abs(b.contribution) - Math.abs(a.contribution))
          .map((c) => (
            <tr key={c.feature}>
              <Td align="left">
                <span className="text-ink">{featureLabel(c.feature)}</span>
                <span className="block max-w-md text-xs whitespace-normal text-muted">{c.description}</span>
              </Td>
              <Td>{fmtNum(c.value, 2)}</Td>
              <Td>{fmtSigned(c.contribution, 2)}</Td>
            </tr>
          ))}
      </tbody>
    </TableWrap>
  )
}
