import { type ThreadMessage, type useLocalRuntime } from "@assistant-ui/react"
import { useCallback, useEffect, useRef, useState } from "react"

import {
  addMessages,
  fetchConversation,
  fetchConversations,
  startConversation,
  type ChatMessage,
  type ConversationSummary,
} from "@/lib/conversations"

type Runtime = ReturnType<typeof useLocalRuntime>

function stored(message: ThreadMessage): ChatMessage {
  return {
    role: message.role === "user" ? "user" : "assistant",
    text: message.content
      .map((part) => (part.type === "text" ? part.text : ""))
      .join("\n"),
    blocked: message.metadata.custom?.blocked === true,
  }
}

// Keeps the chat's conversations on the server: each message, once it's
// finished, goes to the open conversation, and the first starts a new one.
// open() brings a conversation back into the chat. headers go with each
// request.
export function useChatHistory(
  runtime: Runtime,
  headers: Record<string, string>
) {
  const [conversations, setConversations] = useState<ConversationSummary[]>([])
  const [current, setCurrent] = useState<string | null>(null)
  const sync = useRef({
    id: null as string | null,
    // The messages on the server, or on their way there.
    saved: new Set<string>(),
    // Counts the chats: a save for a chat that's gone doesn't open it again.
    chat: 0,
    // While open() loads a conversation into the chat.
    loading: false,
    saving: Promise.resolve(),
  })
  // The headers of the first render: the chat remounts for another account.
  const [sent] = useState(headers)

  const refresh = useCallback(
    () => fetchConversations(sent).then(setConversations, () => {}),
    [sent]
  )

  const open = useCallback(
    async (id: string) => {
      const conversation = await fetchConversation(id, sent)
      const state = sync.current
      state.chat += 1
      state.loading = true
      runtime.thread.reset(
        conversation.messages.map((m) => ({
          role: m.role,
          content: [{ type: "text" as const, text: m.text }],
          metadata: { custom: { blocked: m.blocked } },
        }))
      )
      for (const message of runtime.thread.getState().messages)
        state.saved.add(message.id)
      state.loading = false
      state.id = id
      setCurrent(id)
    },
    [runtime, sent]
  )

  useEffect(() => {
    void refresh()
  }, [refresh])

  useEffect(
    () =>
      runtime.thread.subscribe(() => {
        const state = sync.current
        const messages = runtime.thread.getState().messages
        if (state.loading) {
          for (const message of messages) state.saved.add(message.id)
          return
        }
        if (!messages.length) {
          if (state.id) setCurrent(null)
          state.id = null
          state.chat += 1
          return
        }
        const fresh: ThreadMessage[] = []
        for (const message of messages) {
          if (state.saved.has(message.id)) continue
          if (message.role === "system") continue
          // Later messages wait for the answer still being written.
          if (message.role === "assistant" && message.status.type === "running")
            break
          fresh.push(message)
        }
        if (!fresh.length) return
        for (const message of fresh) state.saved.add(message.id)
        const items = fresh.map(stored)
        const chat = state.chat
        state.saving = state.saving
          .then(async () => {
            if (chat !== state.chat) return
            if (state.id) {
              await addMessages(state.id, items, sent)
            } else {
              const started = await startConversation(items, sent)
              if (chat !== state.chat) return
              state.id = started.id
              setCurrent(started.id)
            }
            await refresh()
          })
          .catch(() => {})
      }),
    [runtime, refresh, sent]
  )

  return { conversations, current, open }
}
