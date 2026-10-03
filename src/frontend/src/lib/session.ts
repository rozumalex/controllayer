import { createContext, useContext } from "react"

import type { Employee } from "@/lib/policy"

export type Session = { user: Employee; signOut: () => void }

export const SessionContext = createContext<Session | null>(null)

// The signed-in user, or null outside the sign-in gate.
export const useSession = () => useContext(SessionContext)
