import { userHeaders } from "@/lib/users"

// The first rule whose claim holds the value sets the role, see role_for in
// the backend.
export type RoleRule = {
  claim: string
  value: string
  role: string
  admin: boolean
}

export type IdentityProvider = {
  name: string
  issuer: string
  client_id: string
  has_secret: boolean
  scopes: string
  domains: string[]
  role_rules: RoleRule[]
  default_role: string | null
  enabled: boolean
  redirect_uri: string
}

// What saving sends: no secret keeps the saved one, an empty one removes it.
export type IdentityProviderWrite = Omit<
  IdentityProvider,
  "has_secret" | "redirect_uri"
> & { client_secret?: string }

export type ScimStatus = { base_url: string; has_token: boolean }

// Shown once: only its hash is stored.
export type ScimToken = { token: string; base_url: string }

const URL = "/api/identity-provider"

async function request<T>(init: RequestInit = {}, path = ""): Promise<T> {
  const response = await fetch(URL + path, {
    ...init,
    headers: { "Content-Type": "application/json", ...userHeaders() },
  })
  if (response.status === 204) return undefined as T
  const body = await response.json().catch(() => null)
  if (!response.ok) {
    const detail = body?.detail
    throw new Error(
      Array.isArray(detail)
        ? detail.map((e: { msg: string }) => e.msg).join("; ")
        : (detail ?? `The request failed with ${response.status}.`)
    )
  }
  return body as T
}

export const fetchProvider = () => request<IdentityProvider | null>()

export const saveProvider = (provider: IdentityProviderWrite) =>
  request<IdentityProvider>({ method: "PUT", body: JSON.stringify(provider) })

export const deleteProvider = () => request<void>({ method: "DELETE" })

export const fetchScim = () => request<ScimStatus>({}, "/scim")

export const newScimToken = () =>
  request<ScimToken>({ method: "POST" }, "/scim-token")
