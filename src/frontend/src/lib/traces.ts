import { userHeaders } from "@/lib/users"

// The responses of GET /api/traces, see app/core/schema/traces.py.

export type Outcome =
  "allowed" | "suspicious" | "flagged" | "blocked" | "error" | "unlocked"

type Usage = {
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
}

type Finding = {
  guard: string
  action: string
  reason: string
  score: number | null
  direction: string
  tool: string
}

export type TraceSummary = {
  trace_id: string
  started_at: string
  agent_id: string | null
  user: { id: string; name: string } | null
  prompt: string | null
  outcome: Outcome
  findings: Finding[]
  usage: Usage
  // What the model's tokens cost, in US dollars.
  usd: string
  duration_ms: number
}

type Stats = {
  requests: number
  blocked: number
  flagged: number
  errors: number
  usage: Usage
}

export type TraceList = { stats: Stats; traces: TraceSummary[] }

export type TraceEvent = {
  id: number
  event: string
  action: string | null
  created_at: string
  data: Record<string, unknown>
}

export type TraceDetail = { summary: TraceSummary; events: TraceEvent[] }

async function get<T>(url: string): Promise<T> {
  const response = await fetch(url, { headers: userHeaders() })
  if (!response.ok) throw new Error(`${url} failed with ${response.status}.`)
  return response.json()
}

export const fetchTraces = (limit = 100) =>
  get<TraceList>(`/api/traces?limit=${limit}`)

export const fetchTrace = (traceId: string) =>
  get<TraceDetail>(`/api/traces/${encodeURIComponent(traceId)}`)

export type Range = "1h" | "24h" | "7d"

type Bucket = {
  start: string
  allowed: number
  suspicious: number
  flagged: number
  blocked: number
  error: number
  prompt_tokens: number
  completion_tokens: number
  p50_ms: number | null
  p95_ms: number | null
}

type FindingCount = { guard: string; reason: string; count: number }

export type Analytics = {
  range: Range
  bucket_seconds: number
  timeline: Bucket[]
  findings: FindingCount[]
}

export const fetchAnalytics = (range: Range) =>
  get<Analytics>(`/api/traces/analytics?range=${range}`)

export type ExportFormat = "csv" | "json"

export type ExportFilters = {
  format: ExportFormat
  start?: Date
  outcomes: Outcome[]
  guard?: string
}

// Downloads GET /api/traces/export. A plain link can't send the user header,
// so it fetches the file and saves it from a blob.
export async function downloadTraces(filters: ExportFilters) {
  const query = new URLSearchParams({ format: filters.format })
  if (filters.start) query.set("start", filters.start.toISOString())
  for (const outcome of filters.outcomes) query.append("outcome", outcome)
  if (filters.guard) query.set("guard", filters.guard)
  const response = await fetch(`/api/traces/export?${query}`, {
    headers: userHeaders(),
  })
  if (!response.ok)
    throw new Error(`The export failed with ${response.status}.`)
  const name = /filename="([^"]+)"/.exec(
    response.headers.get("Content-Disposition") ?? ""
  )?.[1]
  const url = URL.createObjectURL(await response.blob())
  const link = document.createElement("a")
  link.href = url
  link.download = name ?? `audit-log.${filters.format}`
  link.click()
  URL.revokeObjectURL(url)
}
