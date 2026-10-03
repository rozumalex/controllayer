import { Chat } from "@/components/chat"
import { Config } from "@/components/config"
import { Dashboard } from "@/components/dashboard"

// A few pages, so the path picks one; no router needed. The host serves
// index.html for every path.
function App() {
  const path = window.location.pathname
  if (path.startsWith("/dashboard")) return <Dashboard />
  if (path.startsWith("/config")) return <Config />
  return <Chat />
}

export default App
