import { LogOut } from "lucide-react"
import {
  useEffect,
  useRef,
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
  signIn,
  signInToDemo,
  signInWithGoogle,
  signOut,
  signUp,
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

function SignIn({ onSignedIn }: { onSignedIn: (user: Employee) => void }) {
  const [mode, setMode] = useState<"sign-in" | "sign-up">("sign-in")
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const organization = useRef<HTMLInputElement>(null)
  const signingUp = mode === "sign-up"

  async function run(action: () => Promise<Employee>) {
    setBusy(true)
    setError(null)
    try {
      onSignedIn(await action())
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  function google(credential: string) {
    const name = organization.current?.value.trim()
    if (signingUp && !name) {
      setError("Name your organization first, then continue with Google.")
      return
    }
    void run(() => signInWithGoogle(credential, signingUp ? name : undefined))
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const field = (name: string) => String(form.get(name) ?? "")
    void run(() =>
      signingUp
        ? signUp({
            organization: field("organization"),
            name: field("name"),
            email: field("email"),
            password: field("password"),
          })
        : signIn(field("email"), field("password"))
    )
  }

  return (
    <div className="flex min-h-svh items-start justify-center bg-muted/40 px-4 py-16">
      <div className="flex w-full max-w-sm animate-in flex-col gap-6 duration-200 fade-in slide-in-from-bottom-1">
        <div className="flex flex-col gap-3">
          <Logo className="size-12" />
          <h1 className="font-serif text-3xl font-semibold tracking-tight text-primary">
            {signingUp ? "Start an organization" : "Sign in"}
          </h1>
          <p className="text-muted-foreground">
            {signingUp
              ? "Put your agents behind the AI control layer. Colleagues join by invitation."
              : "Sign in to the AI control layer."}
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

        {googleEnabled && <Divider>or</Divider>}
        {signingUp && (
          // Outside the form, as Google sign-up needs it too; the form
          // attribute still sends it with the form.
          <Field
            key="organization"
            ref={organization}
            name="organization"
            label="Organization"
            form="credentials"
            autoFocus
          />
        )}
        <GoogleButton
          text={signingUp ? "signup_with" : "signin_with"}
          onCredential={google}
        />
        <Divider>or with your email</Divider>

        <form
          id="credentials"
          key={mode}
          onSubmit={submit}
          className="flex flex-col gap-4"
        >
          {signingUp && (
            <Field name="name" label="Your name" autoComplete="name" />
          )}
          <Field
            name="email"
            label="Email"
            type="email"
            autoComplete="email"
            autoFocus={!signingUp}
          />
          <Field
            name="password"
            label="Password"
            type="password"
            minLength={signingUp ? 8 : undefined}
            autoComplete={signingUp ? "new-password" : "current-password"}
          />
          {error && <p className="text-sm text-destructive">{error}</p>}
          <Button type="submit" variant="outline" disabled={busy}>
            {signingUp ? "Create the organization" : "Sign in"}
          </Button>
        </form>

        <p className="text-center text-sm text-muted-foreground">
          {signingUp ? "Have an account?" : "New here?"}{" "}
          <Button
            variant="link"
            className="h-auto p-0"
            onClick={() => {
              setError(null)
              setMode(signingUp ? "sign-in" : "sign-up")
            }}
          >
            {signingUp ? "Sign in" : "Start an organization"}
          </Button>
        </p>
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
