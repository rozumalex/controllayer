import { useEffect, useState, type ReactNode } from "react"
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Line,
  LineChart,
  XAxis,
  YAxis,
} from "recharts"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart"
import { formatDuration, formatNumber } from "@/lib/format"
import { fetchAnalytics, type Analytics, type Range } from "@/lib/traces"

const REFRESH_MS = 5000

const RANGES: { value: Range; label: string }[] = [
  { value: "1h", label: "Last hour" },
  { value: "24h", label: "24 hours" },
  { value: "7d", label: "7 days" },
]

// Outcomes mean good or bad, so they wear the fixed status colors. Error is a
// model failure, not a guard's call, so it stays neutral gray. Stacked in this
// order, every adjacent pair stays apart for color-blind readers too.
const outcomes = {
  allowed: { label: "Allowed", color: "#0ca30c" },
  flagged: { label: "Flagged", color: "#fab219" },
  blocked: { label: "Blocked", color: "#d03b3b" },
  error: { label: "Error", color: "#898781" },
} satisfies ChartConfig

const requests = {
  total: { label: "Requests", color: "var(--primary)" },
  ...outcomes,
} satisfies ChartConfig

// Plain series: the first two categorical slots.
const tokens = {
  prompt_tokens: { label: "Prompt", color: "#2a78d6" },
  completion_tokens: { label: "Completion", color: "#eb6834" },
} satisfies ChartConfig

const latency = {
  p50_ms: { label: "Median", color: "#2a78d6" },
  p95_ms: { label: "95th percentile", color: "#eb6834" },
} satisfies ChartConfig

const findings = {
  count: { label: "Findings", color: "#2a78d6" },
} satisfies ChartConfig

function useAnalytics(range: Range) {
  const [data, setData] = useState<Analytics | null>(null)

  useEffect(() => {
    let current = true
    const load = () =>
      fetchAnalytics(range)
        .then((data) => current && setData(data))
        .catch(() => {})
    void load()
    const timer = setInterval(load, REFRESH_MS)
    return () => {
      current = false
      clearInterval(timer)
    }
  }, [range])

  // The last data loaded may be for the range before.
  return data?.range === range ? data : null
}

function tickFormatter(range: Range) {
  return (iso: string) =>
    new Date(iso).toLocaleString([], {
      ...(range === "7d" && { weekday: "short" }),
      hour: "2-digit",
      minute: "2-digit",
    })
}

function ChartCard({
  title,
  description,
  className,
  children,
}: {
  title: string
  description: string
  className?: string
  children: ReactNode
}) {
  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <p className="text-sm text-muted-foreground">{description}</p>
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  )
}

const axis = { tickLine: false, axisLine: false, tickMargin: 8 } as const

// Axis ticks wrap at spaces, so they leave the space out.
const formatTickDuration = (ms: number) => formatDuration(ms).replace(" ", "")

export function AnalyticsCharts() {
  const [range, setRange] = useState<Range>("1h")
  const data = useAnalytics(range)
  const timeline = data?.timeline ?? []
  const totals = timeline.map((bucket) => ({
    ...bucket,
    total: bucket.allowed + bucket.flagged + bucket.blocked + bucket.error,
  }))
  const formatTick = tickFormatter(range)
  // The tooltip's title: the bucket's start, from the hovered row.
  const labelFormatter = (
    _: unknown,
    payload: readonly { payload?: { start?: string } }[]
  ) => {
    const start = payload[0]?.payload?.start
    return start ? formatTick(start) : ""
  }

  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="font-serif text-xl font-semibold tracking-tight text-primary">
          Analytics
        </h2>
        <div className="flex gap-1 rounded-lg border bg-card p-1">
          {RANGES.map(({ value, label }) => (
            <Button
              key={value}
              size="sm"
              variant={range === value ? "secondary" : "ghost"}
              onClick={() => setRange(value)}
            >
              {label}
            </Button>
          ))}
        </div>
      </div>

      <ChartCard
        title="Requests over time"
        description="Every request through the control layer, by what the layer did."
      >
        <ChartContainer config={requests} className="aspect-auto h-64 w-full">
          <ComposedChart data={totals}>
            <CartesianGrid vertical={false} />
            <XAxis
              dataKey="start"
              {...axis}
              tickFormatter={formatTick}
              minTickGap={32}
            />
            <YAxis {...axis} allowDecimals={false} width={32} />
            <ChartTooltip
              content={<ChartTooltipContent labelFormatter={labelFormatter} />}
            />
            <ChartLegend content={<ChartLegendContent />} itemSorter={null} />
            {/* One line for the total. The area under it is stacked by
                outcome, so each band is one outcome's share. */}
            {(Object.keys(outcomes) as (keyof typeof outcomes)[]).map((key) => (
              <Area
                key={key}
                dataKey={key}
                stackId="outcome"
                type="linear"
                fill={`var(--color-${key})`}
                fillOpacity={0.55}
                stroke="none"
                activeDot={false}
              />
            ))}
            <Line
              dataKey="total"
              type="linear"
              stroke="var(--color-total)"
              strokeWidth={2}
              dot={false}
            />
          </ComposedChart>
        </ChartContainer>
      </ChartCard>

      <div className="grid gap-4 lg:grid-cols-3">
        <ChartCard title="Tokens" description="What the model read and wrote.">
          <ChartContainer config={tokens} className="aspect-auto h-52 w-full">
            <AreaChart data={timeline}>
              <CartesianGrid vertical={false} />
              <XAxis
                dataKey="start"
                {...axis}
                tickFormatter={formatTick}
                minTickGap={32}
              />
              <YAxis {...axis} width={40} tickFormatter={formatNumber} />
              <ChartTooltip
                content={
                  <ChartTooltipContent labelFormatter={labelFormatter} />
                }
              />
              <ChartLegend content={<ChartLegendContent />} itemSorter={null} />
              {(Object.keys(tokens) as (keyof typeof tokens)[]).map((key) => (
                <Area
                  key={key}
                  dataKey={key}
                  stackId="tokens"
                  type="linear"
                  fill={`var(--color-${key})`}
                  fillOpacity={0.25}
                  stroke={`var(--color-${key})`}
                  strokeWidth={2}
                />
              ))}
            </AreaChart>
          </ChartContainer>
        </ChartCard>

        <ChartCard
          title="Response time"
          description="How long a request took, guards and model together."
        >
          <ChartContainer config={latency} className="aspect-auto h-52 w-full">
            <LineChart data={timeline}>
              <CartesianGrid vertical={false} />
              <XAxis
                dataKey="start"
                {...axis}
                tickFormatter={formatTick}
                minTickGap={32}
              />
              <YAxis {...axis} width={56} tickFormatter={formatTickDuration} />
              <ChartTooltip
                content={
                  <ChartTooltipContent
                    labelFormatter={labelFormatter}
                    formatter={(value, name) => (
                      <span className="flex w-full justify-between gap-4">
                        <span className="text-muted-foreground">
                          {latency[name as keyof typeof latency].label}
                        </span>
                        <span className="font-mono tabular-nums">
                          {formatDuration(Number(value))}
                        </span>
                      </span>
                    )}
                  />
                }
              />
              <ChartLegend content={<ChartLegendContent />} itemSorter={null} />
              {(Object.keys(latency) as (keyof typeof latency)[]).map((key) => (
                <Line
                  key={key}
                  dataKey={key}
                  type="linear"
                  stroke={`var(--color-${key})`}
                  strokeWidth={2}
                  dot={{ r: 3, strokeWidth: 0, fill: `var(--color-${key})` }}
                  connectNulls
                />
              ))}
            </LineChart>
          </ChartContainer>
        </ChartCard>

        <ChartCard
          title="Top findings"
          description="What the guards caught most often."
        >
          {data && data.findings.length === 0 ? (
            <p className="flex h-52 items-center justify-center text-sm text-muted-foreground">
              No findings in this range.
            </p>
          ) : (
            <ChartContainer
              config={findings}
              className="aspect-auto h-52 w-full"
            >
              <BarChart
                data={data?.findings.map((f) => ({
                  ...f,
                  label: (
                    f.reason.replace(/^matched: /, "") || f.guard
                  ).replaceAll("_", " "),
                }))}
                layout="vertical"
                margin={{ right: 24 }}
              >
                <CartesianGrid horizontal={false} />
                <XAxis type="number" {...axis} allowDecimals={false} />
                <YAxis type="category" dataKey="label" {...axis} width={112} />
                <ChartTooltip content={<ChartTooltipContent hideIndicator />} />
                <Bar
                  dataKey="count"
                  fill="var(--color-count)"
                  radius={[0, 4, 4, 0]}
                  barSize={18}
                />
              </BarChart>
            </ChartContainer>
          )}
        </ChartCard>
      </div>
    </section>
  )
}
