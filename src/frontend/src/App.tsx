import { Admin } from "@/components/admin"
import { SignedIn } from "@/components/sign-in"
import { Simulator } from "@/components/simulator"
import { isDemo, useSession } from "@/lib/session"

// Two pages, so the path picks one; no router needed. The host serves
// index.html for every path. The root is the sign-in page, which sends a
// signed-in user on to the admin pages. The challenge is only for demo
// accounts, so everyone else goes to the admin pages from it too.
function Page() {
  const demo = isDemo(useSession()?.user)
  const path = window.location.pathname.replace(/^\/simulator/, "/challenge")
  const challenge = demo && path.startsWith("/challenge")
  if (!challenge && !path.startsWith("/admin"))
    window.history.replaceState(null, "", "/admin")
  else if (path !== window.location.pathname)
    window.history.replaceState(null, "", path)
  return challenge ? <Simulator /> : <Admin />
}

function App() {
  return (
    <SignedIn>
      <Page />
    </SignedIn>
  )
}

export default App
