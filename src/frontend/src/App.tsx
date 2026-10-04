import { Admin } from "@/components/admin"
import { Chat } from "@/components/chat"
import { Consent } from "@/components/consent"
import { SignedIn } from "@/components/sign-in"
import { Simulator } from "@/components/simulator"

// A few pages, so the path picks one; no router needed. The host serves
// index.html for every path.
function Page() {
  const path = window.location.pathname
  if (path === "/oauth/authorize") return <Consent />
  if (path.startsWith("/simulator")) return <Simulator />
  return path.startsWith("/admin") ? <Admin /> : <Chat />
}

function App() {
  return (
    <SignedIn>
      <Page />
    </SignedIn>
  )
}

export default App
