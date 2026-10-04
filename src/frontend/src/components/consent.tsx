import { useState } from "react"

import { Logo } from "@/components/brand"
import { Button } from "@/components/ui/button"
import { useSession } from "@/lib/session"
import { userHeaders } from "@/lib/users"

// The last step of the OAuth sign-in of an MCP client, such as Claude: the
// signed-in user lets it use Portcullis as them. The API sends the browser
// here with the client's request, and the answer sends it back to the client.
export function Consent() {
  const session = useSession()
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const params = Object.fromEntries(new URLSearchParams(window.location.search))
  const client = params.client_name || "An MCP client"
  let host = ""
  try {
    host = new URL(params.redirect_uri).host
  } catch {
    // The API refuses the request below.
  }

  async function answer(allow: boolean) {
    setBusy(true)
    setError(null)
    const response = await fetch("/api/oauth/consent", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...userHeaders() },
      body: JSON.stringify({
        ...params,
        explicit: Boolean(params.explicit),
        allow,
      }),
    })
    const body = await response.json().catch(() => null)
    if (response.ok) {
      window.location.assign(body.redirect)
      return
    }
    setError(body?.detail ?? `The request failed with ${response.status}.`)
    setBusy(false)
  }

  if (!session) return null
  return (
    <div className="flex min-h-svh items-start justify-center bg-muted/40 px-4 py-16">
      <div className="flex w-full max-w-sm flex-col gap-6">
        <Logo className="size-12" />
        <h1 className="font-serif text-3xl font-semibold tracking-tight text-primary">
          {client} wants to use Portcullis
        </h1>
        <p className="text-muted-foreground">
          It gets the tools your role allows, as {session.user.name},{" "}
          {session.user.role}. Every call goes through your role&apos;s guards
          and shows in the traces under your name.
        </p>
        <p className="text-sm">
          Allowing sends you back to <span className="font-mono">{host}</span>.
          Only allow it if you started this there.
        </p>
        {error && <p className="text-sm text-destructive">{error}</p>}
        <div className="flex gap-2">
          <Button disabled={busy} onClick={() => answer(true)}>
            Allow
          </Button>
          <Button
            variant="outline"
            disabled={busy}
            onClick={() => answer(false)}
          >
            Deny
          </Button>
        </div>
      </div>
    </div>
  )
}
