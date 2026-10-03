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
    throw new Error(detail ?? `The request failed with ${response.status}.`)
  }
  return response.json()
}

function keep(signed: SignedIn): Employee {
  storeToken(signed.token)
  return signed.user
}

// Emails a sign-in code. The demo account's email signs in at once instead,
// and the user comes back.
export async function sendCode(email: string): Promise<Employee | null> {
  const answer = await post<SignedIn | { sent: true }>("email", { email })
  return "token" in answer ? keep(answer) : null
}

export const signInWithCode = async (email: string, code: string) =>
  keep(await post<SignedIn>("email/verify", { email, code }))

export const signInToDemo = async () => keep(await post<SignedIn>("demo"))

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
