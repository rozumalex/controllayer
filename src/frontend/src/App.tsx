import { Chat } from "@/components/chat"
import { Config } from "@/components/config"
import { Controls } from "@/components/controls"
import { Dashboard } from "@/components/dashboard"
import { SignedIn } from "@/components/sign-in"

// A few pages, so the path picks one; no router needed. The host serves
// index.html for every path.
function Page() {
  const path = window.location.pathname
  if (path.startsWith("/dashboard")) return <Dashboard />
  if (path.startsWith("/config")) return <Config />
  if (path.startsWith("/controls")) return <Controls />
  return <Chat />
}

function App() {
  return (
    <SignedIn>
      <Page />
    </SignedIn>
  )
}

export default App
