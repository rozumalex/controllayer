import type { Employee } from "@/lib/policy"

// The picked user stays in the browser, so a reload keeps them signed in.
const KEY = "user-id"

export function storedUserId(): string | null {
  try {
    return localStorage.getItem(KEY)
  } catch {
    return null
  }
}

export function storeUserId(id: string | null) {
  try {
    if (id) localStorage.setItem(KEY, id)
    else localStorage.removeItem(KEY)
  } catch {
    // Without storage the user picks again after a reload.
  }
}

// The header that names the signed-in user on every API call.
export const userHeaders = (): Record<string, string> => {
  const id = storedUserId()
  return id ? { "User-Id": id } : {}
}

// The stored user, or null if there is none or the server no longer knows them.
export async function fetchMe(): Promise<Employee | null> {
  if (!storedUserId()) return null
  const response = await fetch("/api/employees/me", { headers: userHeaders() })
  if (response.status === 401) return null
  if (!response.ok)
    throw new Error(`Loading the user failed with ${response.status}.`)
  return response.json()
}

// What the sign-in screen shows of an employee, see sign_in_employees.
export type SignInEmployee = Pick<
  Employee,
  "id" | "name" | "role" | "team" | "clearance_level"
>

export async function fetchSignInEmployees(
  q: string
): Promise<SignInEmployee[]> {
  const query = new URLSearchParams({ limit: "12" })
  if (q) query.set("q", q)
  const response = await fetch(`/api/employees/sign-in?${query}`)
  if (!response.ok)
    throw new Error(`Loading the staff failed with ${response.status}.`)
  return response.json()
}

export const initials = (name: string) =>
  name
    .split(/\s+/)
    .map((part) => part[0])
    .slice(0, 2)
    .join("")
    .toUpperCase()
