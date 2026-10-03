import { Chat } from "@/components/chat"
import { Dashboard } from "@/components/dashboard"

// Two pages, so the path picks one; no router needed. The host serves
// index.html for every path.
function App() {
  return window.location.pathname.startsWith("/dashboard") ? (
    <Dashboard />
  ) : (
    <Chat />
  )
}

export default App
