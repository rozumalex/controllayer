import { createContext, useContext } from "react"

import type { Employee } from "@/lib/policy"

export type Session = { user: Employee; signOut: () => void }

export const SessionContext = createContext<Session | null>(null)

// The signed-in user, or null outside the sign-in gate.
export const useSession = () => useContext(SessionContext)

// Only privileged users may open the admin pages; the API checks it too.
export const isPrivileged = (user?: Employee) =>
  user?.clearance_level === "PRIVILEGED"

// Only demo accounts may open the attack challenge; the API checks it too.
export const isDemo = (user?: Employee) => user?.demo === true
