import { Admin } from "@/components/admin"
import { Chat } from "@/components/chat"
import { SignedIn } from "@/components/sign-in"

// Two pages, so the path picks one; no router needed. The host serves
// index.html for every path.
function Page() {
  return window.location.pathname.startsWith("/admin") ? <Admin /> : <Chat />
}

function App() {
  return (
    <SignedIn>
      <Page />
    </SignedIn>
  )
}

export default App
