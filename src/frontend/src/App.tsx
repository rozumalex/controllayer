import { useState } from "react"
import { Button } from "@/components/ui/button"

function App() {
  const [count, setCount] = useState(0)

  return (
    <main className="flex min-h-svh flex-col items-center justify-center gap-4">
      <h1 className="text-2xl font-semibold">Hackathon template</h1>
      <Button onClick={() => setCount((count) => count + 1)}>
        Count is {count}
      </Button>
    </main>
  )
}

export default App
