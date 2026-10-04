import { History, SquarePen } from "lucide-react"
import { useState, type ReactNode } from "react"

import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { type useChatHistory } from "@/hooks/use-chat-history"
import { formatDateTime } from "@/lib/format"
import { cn } from "@/lib/utils"

// A chat with its history: the history button swaps the chat for the list of
// its conversations, the last changed first, and picking one opens it. The
// chat stays mounted, so it keeps its place.
export function ChatHistory({
  history,
  onNew,
  children,
}: {
  history: ReturnType<typeof useChatHistory>
  onNew: () => void
  children: ReactNode
}) {
  const [browsing, setBrowsing] = useState(false)
  const { conversations, current, open } = history
  const title = conversations.find((c) => c.id === current)?.title

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-2 border-b px-2 py-1.5">
        <Button
          size="sm"
          variant={browsing ? "secondary" : "ghost"}
          className="min-w-0 justify-start"
          aria-pressed={browsing}
          onClick={() => setBrowsing((browsing) => !browsing)}
        >
          <History />
          <span className="truncate">
            {browsing ? "Conversations" : (title ?? "New conversation")}
          </span>
        </Button>
      </div>
      {browsing && (
        <ScrollArea className="min-h-0 flex-1">
          <div className="flex flex-col gap-1 p-2">
            <Button
              variant="ghost"
              className="justify-start"
              onClick={() => {
                onNew()
                setBrowsing(false)
              }}
            >
              <SquarePen /> New conversation
            </Button>
            {conversations.length === 0 && (
              <p className="px-3 py-2 text-sm text-muted-foreground">
                No conversations yet
              </p>
            )}
            {conversations.map((c) => (
              <button
                key={c.id}
                type="button"
                className={cn(
                  "flex flex-col items-start rounded-md px-3 py-2 text-left hover:bg-muted",
                  c.id === current && "bg-muted"
                )}
                onClick={() => {
                  void open(c.id)
                  setBrowsing(false)
                }}
              >
                <span className="w-full truncate text-sm">{c.title}</span>
                <span className="text-xs text-muted-foreground">
                  {formatDateTime(c.updated_at)}
                </span>
              </button>
            ))}
          </div>
        </ScrollArea>
      )}
      <div className={cn("min-h-0 flex-1", browsing && "hidden")}>
        {children}
      </div>
    </div>
  )
}
