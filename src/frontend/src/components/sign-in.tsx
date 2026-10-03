import { REGEXP_ONLY_DIGITS } from "input-otp"
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
import {
  InputOTP,
  InputOTPGroup,
  InputOTPSlot,
} from "@/components/ui/input-otp"
import { Label } from "@/components/ui/label"
import type { Employee } from "@/lib/policy"
import { SessionContext, isPrivileged, useSession } from "@/lib/session"
import {
  fetchMe,
  finishSso,
  googleEnabled,
  initials,
  sendCode,
  signInToDemo,
  signInWithCode,
  signInWithGoogle,
  signOut,
  startSso,
} from "@/lib/users"
import { cn } from "@/lib/utils"

// Shows the app to a signed-in user, and the sign-in screen to anyone else.
export function SignedIn({ children }: { children: ReactNode }) {
  // undefined while the stored session loads, null when nobody is signed in.
  const [user, setUser] = useState<Employee | null | undefined>(undefined)
  const [linkFailed, setLinkFailed] = useState(false)

  // A fresh sign-in lands on the admin pages, for those who may open them.
  // A reload stays where it was.
  const signedIn = (user: Employee) => {
    if (isPrivileged(user) && !window.location.pathname.startsWith("/admin"))
      window.history.replaceState(null, "", "/admin")
    setUser(user)
  }

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    // An identity provider sends the browser back here after its sign-in.
    if (window.location.pathname === "/auth/callback") {
      const code = params.get("code")
      const state = params.get("state")
      window.history.replaceState(null, "", "/")
      if (code && state) {
        finishSso(code, state)
          .then(signedIn)
          .catch(() => {
            setLinkFailed(true)
            setUser(null)
          })
        return
      }
    }
    // The link in the sign-in email carries the email and its code.
    const email = params.get("email")
    const code = params.get("code")
    if (email && code) {
      // Out of the address bar and the history, as the code is a secret.
      window.history.replaceState(null, "", window.location.pathname)
      signInWithCode(email, code)
        .then(signedIn)
        .catch(() => {
          setLinkFailed(true)
          setUser(null)
        })
      return
    }
    fetchMe()
      .then(setUser)
      .catch(() => setUser(null))
  }, [])

  if (user === undefined) return null
  if (user === null)
    return (
      <SignIn
        onSignedIn={signedIn}
        initialError={
          linkFailed ? "That sign-in expired or was used. Try again." : null
        }
      />
    )
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
  invalid = false,
  ...props
}: { name: string; label: string; invalid?: boolean } & ComponentProps<
  typeof Input
>) {
  return (
    <div className="flex flex-col gap-2">
      {/* An error takes the label's place, so nothing below moves. */}
      <Label htmlFor={name} className={cn(invalid && "text-destructive")}>
        {label}
      </Label>
      <Input
        id={name}
        name={name}
        required
        aria-invalid={invalid}
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
function SignIn({
  onSignedIn,
  initialError,
}: {
  onSignedIn: (user: Employee) => void
  initialError: string | null
}) {
  // The email a code went to, or null before one is sent.
  const [codeSentTo, setCodeSentTo] = useState<string | null>(null)
  const [code, setCode] = useState("")
  // Not an error: news about the code, such as one sent moments ago.
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(initialError)
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
      // A domain with its own identity provider signs in there instead.
      if (await startSso({ email })) return null
      const answer = await sendCode(email)
      // The demo's email signs in at once; any other gets a code.
      if (typeof answer !== "string") return answer
      setCode("")
      setCodeSentTo(email)
      setNotice(
        answer === "recent"
          ? "A code went out moments ago. Use that one."
          : null
      )
      return null
    })
  }

  function enterCode(value: string) {
    setCode(value)
    // Typing again puts the button back in the message's place.
    setError(null)
    setNotice(null)
    if (value.length === 6 && codeSentTo)
      void run(async () => {
        try {
          return await signInWithCode(codeSentTo, value)
        } catch (e) {
          // Empty boxes, ready for the code typed again.
          setCode("")
          throw e
        }
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
          <Button disabled={busy} onClick={() => run(signInToDemo)}>
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
              label={error ?? "Email"}
              invalid={Boolean(error)}
              type="email"
              autoComplete="email"
            />
            <Button type="submit" disabled={busy}>
              Email me a code
            </Button>
          </form>
        ) : (
          <form
            onSubmit={(e) => {
              e.preventDefault()
              enterCode(code)
            }}
            className="flex flex-col gap-4"
          >
            <div className="flex flex-col gap-2">
              <Label htmlFor="code">The code we sent to {codeSentTo}</Label>
              <InputOTP
                id="code"
                maxLength={6}
                pattern={REGEXP_ONLY_DIGITS}
                value={code}
                onChange={enterCode}
                disabled={busy}
                autoFocus
                containerClassName="justify-center"
              >
                <InputOTPGroup className="gap-1.5 has-aria-invalid:ring-0">
                  {[0, 1, 2, 3, 4, 5].map((index) => (
                    <InputOTPSlot
                      key={index}
                      index={index}
                      aria-invalid={Boolean(error)}
                      className="size-8 rounded-lg border bg-background text-base"
                    />
                  ))}
                </InputOTPGroup>
              </InputOTP>
            </div>
            {/* The code signs in as soon as it is whole. The button's place
                shows a message instead while there is one, so nothing moves. */}
            {busy || error || notice ? (
              <p
                aria-live="polite"
                className={cn(
                  "flex h-8 items-center justify-center text-sm",
                  error ? "text-destructive" : "text-muted-foreground"
                )}
              >
                {busy ? "Signing in…" : (error ?? notice)}
              </p>
            ) : (
              <Button type="submit" disabled={code.length < 6}>
                Sign in
              </Button>
            )}
            <div className="-mt-2 flex justify-between text-sm">
              <Button
                type="button"
                variant="link"
                className="h-auto p-0"
                onClick={() => {
                  setError(null)
                  setNotice(null)
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
