import { LogOut, Search } from "lucide-react"
import { useEffect, useState, type ReactNode } from "react"

import { COMPANY, Logo } from "@/components/brand"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { fetchEmployees, type Employee } from "@/lib/policy"
import { SessionContext, useSession } from "@/lib/session"
import { fetchMe, initials, storeUserId } from "@/lib/users"

// A demo sign-in: the user picks who they are from the staff list. Nothing
// proves it, the pick only names the user to the API.
export function SignedIn({ children }: { children: ReactNode }) {
  // undefined while the stored user loads, null when nobody is signed in.
  const [user, setUser] = useState<Employee | null | undefined>(undefined)

  useEffect(() => {
    fetchMe()
      .then(setUser)
      .catch(() => setUser(null))
  }, [])

  if (user === undefined) return null
  if (user === null) {
    return (
      <SignIn
        onPick={(picked) => {
          storeUserId(picked.id)
          setUser(picked)
        }}
      />
    )
  }
  const signOut = () => {
    storeUserId(null)
    setUser(null)
  }
  return (
    <SessionContext.Provider value={{ user, signOut }}>
      {children}
    </SessionContext.Provider>
  )
}

function SignIn({ onPick }: { onPick: (user: Employee) => void }) {
  const [query, setQuery] = useState("")
  const [users, setUsers] = useState<Employee[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let current = true
    // Waits for a pause in typing, so each key press is not a request.
    const timer = setTimeout(() => {
      fetchEmployees({ q: query.trim(), role: "", limit: 12, offset: 0 })
        .then((found) => {
          if (!current) return
          setUsers(found.employees)
          setError(null)
        })
        .catch((e: Error) => {
          if (current) setError(e.message)
        })
    }, 200)
    return () => {
      current = false
      clearTimeout(timer)
    }
  }, [query])

  return (
    <div className="flex min-h-svh items-start justify-center bg-muted/40 px-4 py-16">
      <div className="flex w-full max-w-xl animate-in flex-col gap-6 duration-200 fade-in slide-in-from-bottom-1">
        <div className="flex flex-col gap-3">
          <Logo className="size-12" />
          <h1 className="font-serif text-3xl font-semibold tracking-tight text-primary">
            Welcome back. Who are you?
          </h1>
          <p className="text-muted-foreground">
            Pick yourself from the {COMPANY} staff to continue.
          </p>
        </div>
        <div className="relative">
          <Search className="absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            autoFocus
            className="bg-background pl-9"
            placeholder="Search by name or email"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        {error && <p className="text-sm text-destructive">{error}</p>}
        <ul className="flex flex-col divide-y overflow-hidden rounded-lg border bg-background">
          {users.map((user) => (
            <li key={user.id}>
              <button
                type="button"
                onClick={() => onPick(user)}
                className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-muted focus-visible:bg-muted focus-visible:outline-none"
              >
                <Avatar>
                  <AvatarFallback>{initials(user.name)}</AvatarFallback>
                </Avatar>
                <span className="flex min-w-0 flex-1 flex-col">
                  <span className="truncate font-medium">{user.name}</span>
                  <span className="truncate text-sm text-muted-foreground">
                    {[user.role, user.team].filter(Boolean).join(" · ")}
                  </span>
                </span>
                {user.clearance_level && (
                  <span className="shrink-0 rounded-full border px-2 py-0.5 text-xs text-muted-foreground">
                    {user.clearance_level.toLowerCase()}
                  </span>
                )}
              </button>
            </li>
          ))}
          {users.length === 0 && !error && (
            <li className="px-4 py-6 text-center text-sm text-muted-foreground">
              No one matches “{query}”.
            </li>
          )}
        </ul>
      </div>
    </div>
  )
}

// The signed-in user in the header, with a way to switch to another one.
export function UserMenu() {
  const session = useSession()
  if (!session) return null
  const { user, signOut } = session
  return (
    <div className="flex items-center gap-2">
      <Avatar size="sm">
        <AvatarFallback className="bg-gold text-primary">
          {initials(user.name)}
        </AvatarFallback>
      </Avatar>
      <span className="hidden text-sm md:inline">{user.name}</span>
      <Button
        variant="ghost"
        size="icon"
        className="size-8 text-primary-foreground hover:bg-primary-foreground/10 hover:text-primary-foreground"
        title="Switch user"
        onClick={signOut}
      >
        <LogOut className="size-4" />
      </Button>
    </div>
  )
}
