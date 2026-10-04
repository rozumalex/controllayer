import type { Employee } from "@/lib/policy"

// The session token stays in the browser, so a reload keeps the user signed
// in.
const KEY = "session-token"

export function storedToken(): string | null {
  try {
    return localStorage.getItem(KEY)
  } catch {
    return null
  }
}

export function storeToken(token: string | null) {
  try {
    if (token) localStorage.setItem(KEY, token)
    else localStorage.removeItem(KEY)
  } catch {
    // Without storage the user signs in again after a reload.
  }
}

// The browser's own demo sandbox: a random key, made once and kept, that
// signs in to the same copy of the demo bank after a reload. Without storage
// each sign-in gets a new sandbox.
const DEMO_KEY = "demo-key"

function demoKey(): string {
  try {
    const kept = localStorage.getItem(DEMO_KEY)
    if (kept) return kept
  } catch {
    // Made again below.
  }
  const bytes = crypto.getRandomValues(new Uint8Array(32))
  const key = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("")
  try {
    localStorage.setItem(DEMO_KEY, key)
  } catch {
    // This sign-in still works, in a sandbox of its own.
  }
  return key
}

// The header that signs in every API call.
export const userHeaders = (): Record<string, string> => {
  const token = storedToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

// The signed-in user, or null if there is no token or it has expired.
export async function fetchMe(): Promise<Employee | null> {
  if (!storedToken()) return null
  const response = await fetch("/api/employees/me", { headers: userHeaders() })
  if (response.status === 401) return null
  if (!response.ok)
    throw new Error(`Loading the user failed with ${response.status}.`)
  return response.json()
}

// What a sign-in returns, see SignedIn in the backend.
type SignedIn = { token: string; user: Employee }

// A failed request, with its HTTP status.
class RequestError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

async function post<T>(
  path: string,
  body?: Record<string, string>
): Promise<T> {
  const response = await fetch(`/api/auth/${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body && JSON.stringify(body),
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({}))
    const detail = Array.isArray(error.detail)
      ? error.detail[0]?.msg
      : error.detail
    throw new RequestError(
      detail ?? `The request failed with ${response.status}.`,
      response.status
    )
  }
  return response.json()
}

function keep(signed: SignedIn): Employee {
  storeToken(signed.token)
  return signed.user
}

// Emails a sign-in code: "sent", or "recent" when one went out moments ago
// and still works. The demo account's email signs in at once instead, and
// the user comes back.
export async function sendCode(
  email: string
): Promise<Employee | "sent" | "recent"> {
  try {
    const answer = await post<SignedIn | { sent: true }>("email", {
      email,
      demo_key: demoKey(),
    })
    return "token" in answer ? keep(answer) : "sent"
  } catch (e) {
    if (e instanceof RequestError && e.status === 429) return "recent"
    throw e
  }
}

export const signInWithCode = async (email: string, code: string) =>
  keep(await post<SignedIn>("email/verify", { email, code }))

export const signInToDemo = async () =>
  keep(await post<SignedIn>("demo", { key: demoKey() }))

// Sends the browser to the organization's identity provider, which sends it
// back to /auth/callback. False when no provider signs in this email.
export async function startSso(fields: {
  organization?: string
  email?: string
}): Promise<boolean> {
  try {
    const { url } = await post<{ url: string }>("sso", fields)
    try {
      sessionStorage.setItem(
        RETURN_KEY,
        window.location.pathname + window.location.search
      )
    } catch {
      // Without storage the user lands on the home page.
    }
    window.location.assign(url)
    return true
  } catch (e) {
    if (e instanceof RequestError && e.status === 404) return false
    throw e
  }
}

// Where the browser was before single sign-on, such as an MCP client's
// consent page, to go back to after it.
const RETURN_KEY = "sso-return-path"

export function takeReturnPath(): string {
  try {
    const path = sessionStorage.getItem(RETURN_KEY)
    sessionStorage.removeItem(RETURN_KEY)
    // Only a path on this site, never another one.
    return path?.startsWith("/") && !path.startsWith("//") ? path : "/"
  } catch {
    return "/"
  }
}

export const finishSso = async (code: string, state: string) =>
  keep(await post<SignedIn>("sso/callback", { code, state }))

// Whether Sign in with Google is on, see GoogleButton.
export const googleEnabled = Boolean(import.meta.env.VITE_GOOGLE_CLIENT_ID)

export const signInWithGoogle = async (credential: string) =>
  keep(await post<SignedIn>("google", { credential }))

export async function signOut() {
  await fetch("/api/auth/sign-out", {
    method: "POST",
    headers: userHeaders(),
  }).catch(() => undefined)
  storeToken(null)
}

export const initials = (name: string) =>
  name
    .split(/\s+/)
    .map((part) => part[0])
    .slice(0, 2)
    .join("")
    .toUpperCase()
