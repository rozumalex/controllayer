import { userHeaders } from "@/lib/users"

// The API at /api/mcp-servers, see app/core/schema/mcp_servers.py.

export type McpServer = {
  id: string
  name: string
  url: string
  enabled: boolean
  has_auth: boolean
  created_at: string
}

export type McpServerCreate = {
  name: string
  url: string
  auth_header: string | null
}

export type McpTool = {
  name: string
  description: string | null
  input_schema: Record<string, unknown>
  read_only: boolean | null
  destructive: boolean | null
  // Differs from the approved definition, so agents don't get it.
  changed: boolean
}

const URL = "/api/mcp-servers"

// FastAPI puts the reason in detail: a string, or a list of field errors.
function reason(body: unknown, status: number) {
  const detail = (body as { detail?: unknown } | null)?.detail
  if (typeof detail === "string") return detail
  if (Array.isArray(detail)) {
    return detail
      .map((e: { loc?: unknown[]; msg?: string }) =>
        [e.loc?.at(-1), e.msg].filter(Boolean).join(": ")
      )
      .join("; ")
  }
  return `The request failed with ${status}.`
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...userHeaders() },
  })
  if (response.status === 204) return undefined as T
  const body = await response.json().catch(() => null)
  if (!response.ok) throw new Error(reason(body, response.status))
  return body as T
}

export const listServers = () => request<McpServer[]>("")

export const createServer = (server: McpServerCreate) =>
  request<McpServer>("", { method: "POST", body: JSON.stringify(server) })

export const setEnabled = (id: string, enabled: boolean) =>
  request<McpServer>(`/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ enabled }),
  })

export const deleteServer = (id: string) =>
  request<void>(`/${id}`, { method: "DELETE" })

export const approveTools = (id: string) =>
  request<McpServer>(`/${id}/approve`, { method: "POST" })

export const listTools = (id: string) => request<McpTool[]>(`/${id}/tools`)
