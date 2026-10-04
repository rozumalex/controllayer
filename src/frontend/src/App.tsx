import { Admin } from "@/components/admin"
import { SignedIn } from "@/components/sign-in"
import { Simulator } from "@/components/simulator"
import { isPrivileged, useSession } from "@/lib/session"

// Two pages, so the path picks one; no router needed. The host serves
// index.html for every path. The root is the sign-in page, which sends a
// signed-in user on to the admin pages, or to the challenge when they may
// not open them.
function Page() {
  const session = useSession()
  const path = window.location.pathname
  if (path.startsWith("/simulator"))
    window.history.replaceState(null, "", "/challenge")
  else if (!path.startsWith("/admin") && !path.startsWith("/challenge"))
    window.history.replaceState(
      null,
      "",
      isPrivileged(session?.user) ? "/admin" : "/challenge"
    )
  return window.location.pathname.startsWith("/admin") ? (
    <Admin />
  ) : (
    <Simulator />
  )
}

function App() {
  return (
    <SignedIn>
      <Page />
    </SignedIn>
  )
}

export default App
