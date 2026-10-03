// The policy API, see app/core/schema/policy.py.

export const CLEARANCES = [
  "PUBLIC",
  "INTERNAL",
  "CONFIDENTIAL",
  "RESTRICTED",
] as const
export type Clearance = (typeof CLEARANCES)[number]

export const TOOL_ACTIONS = ["allow", "redact", "block"] as const
export type ToolAction = (typeof TOOL_ACTIONS)[number]

export type Budget = {
  monthly_tokens: number | null
  // A decimal string, so cents stay exact.
  monthly_usd: string | null
}

export type PolicySettings = {
  injection_threshold: number
  clearance: Clearance
  above_clearance: ToolAction
  allowed_models: string[]
  budget: Budget
  default_tool_action: ToolAction
  tools: Record<string, ToolAction>
}

export type PolicyRead = { customized: boolean; settings: PolicySettings }

export type RolePolicy = PolicyRead & { role: string; employees: number }

export type PolicyOverview = {
  models: string[]
  default: PolicyRead
  roles: RolePolicy[]
}

export type GatewayTool = {
  name: string
  description: string | null
  read_only: boolean
  destructive: boolean
}

export type Employee = {
  id: string
  name: string
  email: string
  role: string
  division: string | null
  team: string | null
  office: string | null
  clearance_level: string | null
  employment_status: string | null
}

export type EmployeeList = { total: number; employees: Employee[] }

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  if (!response.ok) {
    // FastAPI puts the reason in detail: a string, or a list of field errors.
    const body = await response.json().catch(() => null)
    const detail = Array.isArray(body?.detail)
      ? body.detail.map((e: { msg: string }) => e.msg).join("; ")
      : (body?.detail ?? `failed with ${response.status}`)
    throw new Error(detail)
  }
  return response.status === 204 ? (undefined as T) : response.json()
}

// null is the default policy; a string is a role.
const policyUrl = (role: string | null) =>
  role === null
    ? "/api/policy/default"
    : `/api/policy/roles/${encodeURIComponent(role)}`

export const fetchPolicy = () => request<PolicyOverview>("/api/policy")

export const fetchTools = () => request<GatewayTool[]>("/api/policy/tools")

export const savePolicy = (role: string | null, settings: PolicySettings) =>
  request<PolicyRead>(policyUrl(role), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settings),
  })

export const resetPolicy = (role: string | null) =>
  request<void>(policyUrl(role), { method: "DELETE" })

export function fetchEmployees(params: {
  q: string
  role: string
  limit: number
  offset: number
}) {
  const query = new URLSearchParams({
    limit: String(params.limit),
    offset: String(params.offset),
  })
  if (params.q) query.set("q", params.q)
  if (params.role) query.set("role", params.role)
  return request<EmployeeList>(`/api/employees?${query}`)
}
