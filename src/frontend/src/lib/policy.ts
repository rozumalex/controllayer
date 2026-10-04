import { userHeaders } from "@/lib/users"

// The policy API, see app/core/schema/policy.py.

export const CLEARANCES = [
  "PUBLIC",
  "INTERNAL",
  "CONFIDENTIAL",
  "RESTRICTED",
] as const
export type Clearance = (typeof CLEARANCES)[number]

// The PII the sensitive data guard finds in free text, with the catalog level
// of the field that holds it, see app/control/guards/sensitive_data.py.
export const PII = [
  { kind: "email", label: "Email", level: "CONFIDENTIAL" },
  { kind: "phone", label: "Phone", level: "CONFIDENTIAL" },
  { kind: "iban", label: "IBAN", level: "RESTRICTED" },
  { kind: "payment_card", label: "Payment card", level: "RESTRICTED" },
  { kind: "pesel", label: "PESEL", level: "RESTRICTED" },
] as const satisfies readonly {
  kind: string
  label: string
  level: Clearance
}[]
export type PiiKind = (typeof PII)[number]["kind"]

export const TOOL_ACTIONS = ["allow", "redact", "block"] as const
export type ToolAction = (typeof TOOL_ACTIONS)[number]

// What happens to a kind of PII: the policy's action for it, or, if it names
// none, the action for data above the clearance when the kind is above it.
export function piiAction(
  settings: PolicySettings,
  kind: PiiKind,
  level: Clearance
): ToolAction {
  const fallback =
    CLEARANCES.indexOf(level) > CLEARANCES.indexOf(settings.clearance)
      ? settings.above_clearance
      : "allow"
  return settings.pii[kind] ?? fallback
}

// US dollars a week, from Monday (UTC). A decimal string, so cents stay
// exact; null is unlimited.
export type Budget = { weekly_usd: string | null }

// The budget in a few words, such as "$2 / week".
export const budgetLabel = (budget: Budget) =>
  budget.weekly_usd != null ? `$${budget.weekly_usd} / week` : "Unlimited"

export type PolicySettings = {
  injection_threshold: number
  clearance: Clearance
  above_clearance: ToolAction
  pii: Partial<Record<PiiKind, ToolAction>>
  allowed_models: string[]
  budget: Budget
  // Blocked attacks in a window of minutes that lock an employee out.
  lockout: { blocks: number; flags: number; minutes: number }
  default_tool_action: ToolAction
  tools: Record<string, ToolAction>
  // Whether agents see the blocked tools, marked as blocked.
  show_blocked_tools: boolean
}

export type PolicyRead = { customized: boolean; settings: PolicySettings }

type RolePolicy = PolicyRead & {
  role: string
  employees: number
  // The organization's IdP gives the role, so it may have no people yet.
  from_idp: boolean
}

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
  // False once the IdP deactivates or deletes them.
  active: boolean
}

export type EmployeeList = { total: number; employees: Employee[] }

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: { ...init?.headers, ...userHeaders() },
  })
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
