import { useEffect, useRef } from "react"

// Sign in with Google is off while VITE_GOOGLE_CLIENT_ID is empty. Vite puts
// the value into the built files.
const CLIENT_ID: string | undefined = import.meta.env.VITE_GOOGLE_CLIENT_ID

// The parts of Google Identity Services that the button uses.
type GoogleIdentity = {
  accounts: {
    id: {
      initialize(options: {
        client_id: string
        callback: (response: { credential: string }) => void
      }): void
      renderButton(
        parent: HTMLElement,
        options: { theme: string; size: string; text: string; width: number }
      ): void
    }
  }
}

declare global {
  interface Window {
    google?: GoogleIdentity
  }
}

let script: Promise<void> | undefined

// Loads Google's script once, however many buttons ask for it.
function loadGoogle(): Promise<void> {
  script ??= new Promise((resolve, reject) => {
    const tag = document.createElement("script")
    tag.src = "https://accounts.google.com/gsi/client"
    tag.async = true
    tag.onload = () => resolve()
    tag.onerror = () => reject(new Error("Google sign-in didn't load."))
    document.head.append(tag)
  })
  return script
}

// Google's own button. It hands onCredential the ID token that proves who
// the user is, which the backend checks.
export function GoogleButton({
  text,
  onCredential,
}: {
  text: "signin_with" | "signup_with"
  onCredential: (credential: string) => void
}) {
  const parent = useRef<HTMLDivElement>(null)
  // The latest handler, so a new one doesn't draw the button again.
  const handler = useRef(onCredential)
  useEffect(() => {
    handler.current = onCredential
  })

  useEffect(() => {
    if (!CLIENT_ID) return
    let live = true
    loadGoogle()
      .then(() => {
        const google = window.google
        if (!live || !parent.current || !google) return
        google.accounts.id.initialize({
          client_id: CLIENT_ID,
          callback: ({ credential }) => handler.current(credential),
        })
        google.accounts.id.renderButton(parent.current, {
          theme: "outline",
          size: "large",
          text,
          // Google's button is at most 400 pixels wide.
          width: Math.min(parent.current.offsetWidth, 400),
        })
      })
      .catch(() => undefined)
    return () => {
      live = false
    }
  }, [text])

  if (!CLIENT_ID) return null
  return <div ref={parent} className="flex h-10 w-full justify-center" />
}
