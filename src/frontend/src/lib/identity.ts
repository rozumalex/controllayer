import { userHeaders } from "@/lib/users"

export type ScimStatus = {
  base_url: string
  has_token: boolean
  last_sync_at: string | null
}

// Shown once: only its hash is stored.
export type ScimToken = { token: string; base_url: string }

// A group the IdP synced, and the role its rule gives.
export type DirectoryGroup = {
  name: string
  role: string | null
  members: number
}

export type DirectoryEvent = {
  id: number
  kind:
    | "created"
    | "joined"
    | "left"
    | "role"
    | "deactivated"
    | "reactivated"
    | "synced"
  at: string
  name: string | null
  email: string | null
  data: {
    group?: string
    role?: string | null
    was?: string | null
    sessions?: number
    users?: number
    groups?: number
  }
}

const URL = "/api/identity-provider"

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(URL + path, {
    ...init,
    headers: { "Content-Type": "application/json", ...userHeaders() },
  })
  const body = await response.json().catch(() => null)
  if (!response.ok)
    throw new Error(
      body?.detail ?? `The request failed with ${response.status}.`
    )
  return body as T
}

export const fetchScim = () => request<ScimStatus>("/scim")

export const newScimToken = () =>
  request<ScimToken>("/scim-token", { method: "POST" })

export const fetchGroups = () => request<DirectoryGroup[]>("/groups")

export const fetchLog = () => request<DirectoryEvent[]>("/log?limit=30")
