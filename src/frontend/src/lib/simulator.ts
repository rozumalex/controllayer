import type { PolicySettings } from "@/lib/policy"
import { userHeaders } from "@/lib/users"

// The attack simulator's API, see app/core/schema/demo.py.

export type Account = {
  role: string
  name: string
  policy: PolicySettings
  // Whether the layer locked the account out for too many blocked attacks.
  locked: boolean
  // The ids of the checklist items this account can tick.
  checklist: string[]
}

export type AttackGoal = {
  id: string
  title: string
  description: string
  cases: number
}

export type ChecklistItem = { id: string; title: string; description: string }

// An OWASP Top 10 risk for LLM applications, with the guards whose stops
// count toward it. A risk with no guards isn't covered.
export type Risk = { id: string; title: string; guards: string[] }

export type Simulator = {
  accounts: Account[]
  goals: AttackGoal[]
  checklist: ChecklistItem[]
  risks: Risk[]
}

export type CaseStatus =
  | "blocked"
  | "contained"
  | "landed"
  | "passed"
  | "allowed"
  | "false_alarm"
  | "out_of_budget"
  | "locked_out"

export type Verdict = {
  direction: string
  tool: string
  guard: string
  action: "allow" | "modify" | "block"
  reason: string
  latency_ms: number
}

export type CaseEvent = {
  type: "case"
  id: string
  category: string
  source: string
  mutation: string
  trace_id: string
  // Whether the control layer's protection was on.
  security: boolean
  status: CaseStatus
  // The guard that stopped it, or with security off, would have.
  guard: string | null
  reason: string | null
  // What the attacker sent, and what came back.
  prompt: string
  answer: string
  stolen: number
  // The goals of the hacker's checklist it achieved.
  achieved: string[]
  // The OWASP risk of the attack the layer stopped, or null if it stopped none.
  risk: string | null
  // The case's tokens, and what they cost in dollars.
  tokens: number
  usd: string
  verdicts: Verdict[]
}

export type RunTotals = {
  outcome: "done" | "out_of_budget" | "over_budget" | "locked_out" | "stopped"
  goal: string
  role: string
  security: boolean
  budget: number | null
  cases: number
  blocked: number
  landed: number
  false_alarms: number
  stolen: number
  tokens: number
  usd: string
  guards: Record<string, number>
}

export type EndEvent = { type: "end" } & RunTotals

export type AttackRun = RunTotals & { trace_id: string; created_at: string }

export type AttackRequest = {
  role: string
  goals: string[]
  security: boolean
}

async function get<T>(url: string): Promise<T> {
  const response = await fetch(url, { headers: userHeaders() })
  if (!response.ok) throw new Error(`${url} failed with ${response.status}.`)
  return response.json()
}

export const fetchSimulator = () => get<Simulator>("/api/demo")

// What came of a chat answer through the taken-over account, from its trace
// and the answer. The server keeps it in the account's logs.
export async function chatCase(
  traceId: string,
  answer: string,
  security: boolean
): Promise<CaseEvent> {
  const response = await fetch("/api/demo/chat-case", {
    method: "POST",
    headers: { ...userHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify({ trace_id: traceId, answer, security }),
  })
  if (!response.ok) throw new Error(`The check failed with ${response.status}.`)
  return response.json()
}

// Unlocks an account the layer locked out.
export async function unlock(role: string) {
  const response = await fetch("/api/demo/unlock", {
    method: "POST",
    headers: { ...userHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify({ role }),
  })
  if (!response.ok) throw new Error(`Unlocking failed with ${response.status}.`)
}

// The account's logs: its attack cases and chat answers, oldest first.
export const fetchCases = (role: string) =>
  get<CaseEvent[]>(`/api/demo/cases?role=${encodeURIComponent(role)}`)

// A request the layer checked, as GET /api/demo/history gives it.
export type HistoryEntry = {
  trace_id: string
  created_at: string
  user: string | null
  status: "blocked" | "contained" | "passed" | "allowed"
  guard: string | null
  reason: string | null
  verdicts: Verdict[]
}

export const fetchHistory = () => get<HistoryEntry[]>("/api/demo/history")

export const fetchRuns = () => get<AttackRun[]>("/api/demo/runs")

// Runs an attack and calls onEvent with each line the server streams. Abort
// the signal to stop it. Before each line it waits for wait, which pauses the
// attack: it stops reading, so the server stops once its buffers fill.
export async function runAttack(
  request: AttackRequest,
  onEvent: (event: CaseEvent | EndEvent) => void,
  signal: AbortSignal,
  wait: () => Promise<void> = async () => {}
) {
  const response = await fetch("/api/demo/attack", {
    method: "POST",
    headers: { ...userHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify(request),
    signal,
  })
  if (!response.ok || !response.body)
    throw new Error(`The attack failed with ${response.status}.`)
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader()
  let pending = ""
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    pending += value
    const lines = pending.split("\n")
    pending = lines.pop() ?? ""
    for (const line of lines) {
      if (!line.trim()) continue
      await wait()
      if (signal.aborted) return
      onEvent(JSON.parse(line))
    }
  }
}
