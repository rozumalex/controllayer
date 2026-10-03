import { userHeaders } from "@/lib/users"

// The responses of GET /api/traces, see app/core/schema/traces.py.

export type Outcome = "allowed" | "flagged" | "blocked" | "error"

export type Usage = {
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
}

export type Finding = {
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
  duration_ms: number
}

export type Stats = {
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

export type Bucket = {
  start: string
  allowed: number
  flagged: number
  blocked: number
  error: number
  prompt_tokens: number
  completion_tokens: number
  p50_ms: number | null
  p95_ms: number | null
}

export type FindingCount = { guard: string; reason: string; count: number }

export type Analytics = {
  range: Range
  bucket_seconds: number
  timeline: Bucket[]
  findings: FindingCount[]
}

export const fetchAnalytics = (range: Range) =>
  get<Analytics>(`/api/traces/analytics?range=${range}`)
