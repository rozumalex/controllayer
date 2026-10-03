// The responses of /api/controls, see app/core/schema/controls.py.

export type Direction = "inbound" | "outbound"
export type Mode = "enforce" | "monitor"

export type GuardSettings = {
  enabled: boolean
  mode: Mode
  directions: Direction[]
  threshold: number | null
  disabled_rules: string[]
}

export type Rule = { name: string; score: number; description: string }

export type GuardControl = {
  name: string
  title: string
  description: string
  directions: Direction[]
  blocks: boolean
  scored: boolean
  rules: Rule[]
  customized: boolean
  settings: GuardSettings
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(body?.detail ?? `${url} failed with ${response.status}.`)
  }
  return response.json()
}

const url = (guard: string) => `/api/controls/${encodeURIComponent(guard)}`

export const fetchControls = () => request<GuardControl[]>("/api/controls")

export const saveControl = (guard: string, settings: GuardSettings) =>
  request<GuardControl>(url(guard), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settings),
  })

export const resetControl = (guard: string) =>
  request<GuardControl>(url(guard), { method: "DELETE" })
