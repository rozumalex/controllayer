import { useEffect, useState } from "react"

import { OutcomeBadge } from "@/components/outcome"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { formatDuration, formatNumber } from "@/lib/format"
import {
  fetchTrace,
  type TraceDetail,
  type TraceEvent,
  type TraceSummary,
} from "@/lib/traces"
import { cn } from "@/lib/utils"

// One line on what an event says, by its kind.
function describe({ event, data }: TraceEvent, { user }: TraceSummary): string {
  const usage = data.usage as { total_tokens?: number } | null | undefined
  switch (event) {
    case "request":
      return `from ${user?.name ?? data.agent_id ?? "anonymous"}`
    case "verdict":
      return [
        `${data.guard}: ${data.action}`,
        data.score != null && `score ${data.score}`,
        data.reason,
      ]
        .filter(Boolean)
        .join(" · ")
    case "decision":
      return `${data.direction} ${data.tool}: ${data.action}`
    case "upstream_response":
      return [
        formatDuration(Number(data.latency_ms)),
        usage?.total_tokens != null &&
          `${formatNumber(usage.total_tokens)} tokens`,
      ]
        .filter(Boolean)
        .join(" · ")
    case "upstream_error":
      return `status ${data.status_code}`
    case "response":
      return `finish: ${data.finish_reason}`
    default:
      return ""
  }
}

function dotColor({ event, action }: TraceEvent) {
  if (action === "block") return "bg-destructive"
  if (event === "upstream_error") return "bg-amber-500"
  if (event === "verdict" || event === "decision") return "bg-emerald-500"
  return "bg-primary"
}

function Timeline({
  events,
  summary,
}: {
  events: TraceEvent[]
  summary: TraceSummary
}) {
  const start = new Date(events[0].created_at).getTime()
  return (
    <ol className="relative flex flex-col gap-4 border-l pl-5">
      {events.map((event) => (
        <li key={event.id} className="relative">
          <span
            className={cn(
              "absolute top-1.5 -left-[25px] size-2.5 rounded-full ring-4 ring-background",
              dotColor(event)
            )}
          />
          <div className="flex items-baseline justify-between gap-2">
            <span className="font-mono text-xs font-medium">{event.event}</span>
            <span className="text-xs text-muted-foreground tabular-nums">
              +{formatDuration(new Date(event.created_at).getTime() - start)}
            </span>
          </div>
          <p className="text-sm text-muted-foreground">
            {describe(event, summary)}
          </p>
          <details className="mt-1">
            <summary className="cursor-pointer text-xs text-muted-foreground hover:text-foreground">
              Data
            </summary>
            <pre className="mt-1 max-h-64 overflow-auto rounded-md bg-muted p-2 text-xs">
              {JSON.stringify(event.data, null, 2)}
            </pre>
          </details>
        </li>
      ))}
    </ol>
  )
}

export function TraceSheet({
  traceId,
  onClose,
}: {
  traceId: string | null
  onClose: () => void
}) {
  const [loaded, setLoaded] = useState<TraceDetail | null>(null)

  useEffect(() => {
    if (!traceId) return
    let current = true
    fetchTrace(traceId).then((trace) => current && setLoaded(trace))
    return () => {
      current = false
    }
  }, [traceId])

  // The last trace loaded may be an earlier one, still on its way out.
  const trace = loaded?.summary.trace_id === traceId ? loaded : null
  const summary = trace?.summary
  return (
    <Sheet open={traceId !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-lg">
        <SheetHeader>
          <SheetTitle className="flex items-center gap-2">
            Trace {summary && <OutcomeBadge outcome={summary.outcome} />}
          </SheetTitle>
          <SheetDescription className="font-mono text-xs break-all">
            {traceId}
          </SheetDescription>
        </SheetHeader>
        {trace && summary && (
          <div className="flex flex-col gap-6 px-4 pb-6">
            {summary.prompt && (
              <section>
                <h3 className="mb-1 text-xs font-medium text-muted-foreground uppercase">
                  Prompt
                </h3>
                <p className="rounded-md bg-muted p-3 text-sm whitespace-pre-wrap">
                  {summary.prompt}
                </p>
              </section>
            )}
            <dl className="grid grid-cols-3 gap-3 text-sm">
              <div>
                <dt className="text-xs text-muted-foreground">Duration</dt>
                <dd className="tabular-nums">
                  {formatDuration(summary.duration_ms)}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">Tokens in</dt>
                <dd className="tabular-nums">
                  {formatNumber(summary.usage.prompt_tokens)}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">Tokens out</dt>
                <dd className="tabular-nums">
                  {formatNumber(summary.usage.completion_tokens)}
                </dd>
              </div>
            </dl>
            <section>
              <h3 className="mb-3 text-xs font-medium text-muted-foreground uppercase">
                Timeline
              </h3>
              <Timeline events={trace.events} summary={summary} />
            </section>
          </div>
        )}
      </SheetContent>
    </Sheet>
  )
}
