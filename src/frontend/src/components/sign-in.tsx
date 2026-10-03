import { LogOut } from "lucide-react"
import {
  useEffect,
  useState,
  type ComponentProps,
  type FormEvent,
  type ReactNode,
} from "react"

import { COMPANY, Logo } from "@/components/brand"
import { GoogleButton } from "@/components/google-button"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import type { Employee } from "@/lib/policy"
import { SessionContext, useSession } from "@/lib/session"
import {
  fetchMe,
  googleEnabled,
  initials,
  sendCode,
  signInToDemo,
  signInWithCode,
  signInWithGoogle,
  signOut,
} from "@/lib/users"

// Shows the app to a signed-in user, and the sign-in screen to anyone else.
export function SignedIn({ children }: { children: ReactNode }) {
  // undefined while the stored session loads, null when nobody is signed in.
  const [user, setUser] = useState<Employee | null | undefined>(undefined)

  useEffect(() => {
    fetchMe()
      .then(setUser)
      .catch(() => setUser(null))
  }, [])

  if (user === undefined) return null
  if (user === null) return <SignIn onSignedIn={setUser} />
  const leave = () => {
    void signOut()
    setUser(null)
  }
  return (
    <SessionContext.Provider value={{ user, signOut: leave }}>
      {children}
    </SessionContext.Provider>
  )
}

function Field({
  name,
  label,
  ...props
}: { name: string; label: string } & ComponentProps<typeof Input>) {
  return (
    <div className="flex flex-col gap-2">
      <Label htmlFor={name}>{label}</Label>
      <Input
        id={name}
        name={name}
        required
        className="bg-background"
        {...props}
      />
    </div>
  )
}

function Divider({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-center gap-3 text-xs text-muted-foreground">
      <span className="h-px flex-1 bg-border" />
      {children}
      <span className="h-px flex-1 bg-border" />
    </div>
  )
}

// One screen for everyone: the demo, Google, or a code sent by email. A new
// user's first sign-in creates their account and organization.
function SignIn({ onSignedIn }: { onSignedIn: (user: Employee) => void }) {
  // The email a code went to, or null before one is sent.
  const [codeSentTo, setCodeSentTo] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function run(action: () => Promise<Employee | null>) {
    setBusy(true)
    setError(null)
    try {
      const user = await action()
      if (user) onSignedIn(user)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  function field(event: FormEvent<HTMLFormElement>, name: string) {
    event.preventDefault()
    return String(new FormData(event.currentTarget).get(name) ?? "").trim()
  }

  function askForCode(email: string) {
    void run(async () => {
      const user = await sendCode(email)
      // The demo's email signs in at once; any other gets a code.
      if (!user) setCodeSentTo(email)
      return user
    })
  }

  return (
    <div className="flex min-h-svh items-start justify-center bg-muted/40 px-4 py-16">
      <div className="flex w-full max-w-sm animate-in flex-col gap-6 duration-200 fade-in slide-in-from-bottom-1">
        <div className="flex flex-col gap-3">
          <Logo className="size-12" />
          <h1 className="font-serif text-3xl font-semibold tracking-tight text-primary">
            Sign in to Portcullis
          </h1>
          <p className="text-muted-foreground">
            The control layer for your AI agents. New here? Signing in creates
            your organization.
          </p>
        </div>

        <div className="flex flex-col gap-2">
          <Button size="lg" disabled={busy} onClick={() => run(signInToDemo)}>
            Try the demo
          </Button>
          <p className="text-center text-xs text-muted-foreground">
            Signs you in as a vice president of {COMPANY}, a demo bank.
          </p>
        </div>

        {googleEnabled && (
          <>
            <Divider>or</Divider>
            <GoogleButton
              text="continue_with"
              onCredential={(credential) =>
                run(() => signInWithGoogle(credential))
              }
            />
          </>
        )}
        <Divider>or with your email</Divider>

        {codeSentTo === null ? (
          <form
            onSubmit={(e) => askForCode(field(e, "email"))}
            className="flex flex-col gap-4"
          >
            <Field
              name="email"
              label="Email"
              type="email"
              autoComplete="email"
            />
            {error && <p className="text-sm text-destructive">{error}</p>}
            <Button type="submit" variant="outline" disabled={busy}>
              Email me a code
            </Button>
          </form>
        ) : (
          <form
            onSubmit={(e) => {
              const code = field(e, "code")
              void run(() => signInWithCode(codeSentTo, code))
            }}
            className="flex flex-col gap-4"
          >
            <Field
              name="code"
              label={`The code we sent to ${codeSentTo}`}
              inputMode="numeric"
              autoComplete="one-time-code"
              pattern="\d{6}"
              maxLength={6}
              autoFocus
            />
            {error && <p className="text-sm text-destructive">{error}</p>}
            <Button type="submit" disabled={busy}>
              Sign in
            </Button>
            <div className="flex justify-between text-sm">
              <Button
                type="button"
                variant="link"
                className="h-auto p-0"
                onClick={() => {
                  setError(null)
                  setCodeSentTo(null)
                }}
              >
                Use another email
              </Button>
              <Button
                type="button"
                variant="link"
                className="h-auto p-0"
                disabled={busy}
                onClick={() => askForCode(codeSentTo)}
              >
                Send a new code
              </Button>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}

// The signed-in user in the header, with a way to sign out.
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
        title="Sign out"
        onClick={signOut}
      >
        <LogOut className="size-4" />
      </Button>
    </div>
  )
}
