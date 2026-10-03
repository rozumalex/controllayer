import { useEffect, useState, type ReactNode } from "react"

import { AnalyticsCharts } from "@/components/analytics"
import { ExportDialog } from "@/components/export-dialog"
import { OutcomeBadge } from "@/components/outcome"
import { TraceSheet } from "@/components/trace-sheet"
import {
  Card,
  CardAction,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { formatDuration, formatNumber, formatTime } from "@/lib/format"
import { fetchTraces, type TraceList } from "@/lib/traces"
import { cn } from "@/lib/utils"

const REFRESH_MS = 5000

function useTraces() {
  const [traces, setTraces] = useState<TraceList | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let current = true
    async function load() {
      try {
        const traces = await fetchTraces()
        if (current) {
          setTraces(traces)
          setError(null)
        }
      } catch (error) {
        if (current) setError((error as Error).message)
      }
    }
    void load()
    const timer = setInterval(load, REFRESH_MS)
    return () => {
      current = false
      clearInterval(timer)
    }
  }, [])

  return { traces, error }
}

function Stat({
  label,
  value,
  detail,
  className,
  valueClassName,
}: {
  label: string
  value: ReactNode
  detail?: ReactNode
  className?: string
  valueClassName?: string
}) {
  return (
    <Card size="sm" className={className}>
      <CardHeader>
        <CardTitle className="text-sm font-normal text-muted-foreground">
          {label}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <p
          className={cn("text-3xl font-semibold tabular-nums", valueClassName)}
        >
          {value}
        </p>
        {detail && (
          <p className="mt-1 text-xs text-muted-foreground">{detail}</p>
        )}
      </CardContent>
    </Card>
  )
}

function percent(part: number, whole: number) {
  return whole ? `${Math.round((part / whole) * 100)}% of requests` : "—"
}

export function Dashboard() {
  const { traces, error } = useTraces()
  const [selected, setSelected] = useState<string | null>(null)
  const stats = traces?.stats

  return (
    <>
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="font-serif text-2xl font-semibold tracking-tight text-primary">
            Control layer
          </h1>
          <p className="text-sm text-muted-foreground">
            Every request through the guards, with their verdicts and the tokens
            it used.
          </p>
        </div>
        <span className="flex items-center gap-2 text-xs text-muted-foreground">
          <span
            className={cn(
              "size-2 rounded-full",
              error ? "bg-destructive" : "animate-pulse bg-emerald-500"
            )}
          />
          {error ? "Offline" : "Live"}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        <Stat label="Requests" value={stats ? stats.requests : "—"} />
        <Stat
          label="Blocked"
          value={stats ? stats.blocked : "—"}
          detail={stats && percent(stats.blocked, stats.requests)}
          valueClassName="text-destructive"
        />
        <Stat
          label="Flagged"
          value={stats ? stats.flagged : "—"}
          detail="monitor mode let through"
          valueClassName="text-amber-600"
        />
        <Stat label="Model errors" value={stats ? stats.errors : "—"} />
        <Stat
          className="col-span-2 lg:col-span-1"
          label="Tokens"
          value={stats ? formatNumber(stats.usage.total_tokens) : "—"}
          detail={
            stats &&
            `${formatNumber(stats.usage.prompt_tokens)} in · ${formatNumber(stats.usage.completion_tokens)} out`
          }
        />
      </div>

      <AnalyticsCharts />

      <Card>
        <CardHeader>
          <CardTitle>Recent requests</CardTitle>
          <CardAction>
            <ExportDialog />
          </CardAction>
        </CardHeader>
        <CardContent>
          {error && (
            <p className="mb-3 text-sm text-destructive">
              Could not load the traces: {error}
            </p>
          )}
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-24">Time</TableHead>
                <TableHead className="hidden w-40 lg:table-cell">
                  User
                </TableHead>
                <TableHead>Prompt</TableHead>
                <TableHead className="w-24">Outcome</TableHead>
                <TableHead className="hidden md:table-cell">Findings</TableHead>
                <TableHead className="w-20 text-right">Tokens</TableHead>
                <TableHead className="hidden w-20 text-right sm:table-cell">
                  Time taken
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {traces?.traces.length === 0 && (
                <TableRow>
                  <TableCell
                    colSpan={7}
                    className="py-10 text-center text-muted-foreground"
                  >
                    No requests yet. Send a message in the assistant.
                  </TableCell>
                </TableRow>
              )}
              {traces?.traces.map((trace) => (
                <TableRow
                  key={trace.trace_id}
                  onClick={() => setSelected(trace.trace_id)}
                  className="cursor-pointer"
                >
                  <TableCell className="text-muted-foreground tabular-nums">
                    {formatTime(trace.started_at)}
                  </TableCell>
                  <TableCell className="hidden max-w-0 truncate lg:table-cell">
                    {trace.user?.name ?? (
                      <span className="text-muted-foreground italic">
                        no user
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="max-w-0 truncate">
                    {trace.prompt ?? (
                      <span className="text-muted-foreground italic">
                        not stored
                      </span>
                    )}
                  </TableCell>
                  <TableCell>
                    <OutcomeBadge outcome={trace.outcome} />
                  </TableCell>
                  <TableCell className="hidden max-w-0 truncate text-muted-foreground md:table-cell">
                    {trace.findings
                      .map((f) => `${f.guard}: ${f.reason || f.action}`)
                      .join(", ")}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {formatNumber(trace.usage.total_tokens)}
                  </TableCell>
                  <TableCell className="hidden text-right text-muted-foreground tabular-nums sm:table-cell">
                    {formatDuration(trace.duration_ms)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <TraceSheet traceId={selected} onClose={() => setSelected(null)} />
    </>
  )
}
