import { userHeaders } from "@/lib/users"

// The chat history's API, see app/core/schema/conversations.py. headers go
// with each request, such as the attack simulator's X-Simulate-Role, which
// makes it the history of the employee whose account was taken over.

export type ChatMessage = {
  role: "user" | "assistant"
  text: string
  // Whether the control layer stopped it.
  blocked: boolean
}

export type ConversationSummary = {
  id: string
  title: string
  updated_at: string
}

export type Conversation = ConversationSummary & { messages: ChatMessage[] }

type Headers = Record<string, string>

async function request<T>(
  url: string,
  headers: Headers,
  body?: unknown
): Promise<T> {
  const response = await fetch(url, {
    method: body ? "POST" : "GET",
    headers: {
      ...userHeaders(),
      ...headers,
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!response.ok) throw new Error(`${url} failed with ${response.status}.`)
  return response.status === 204 ? (undefined as T) : response.json()
}

export const fetchConversations = (headers: Headers) =>
  request<ConversationSummary[]>("/api/conversations", headers)

export const fetchConversation = (id: string, headers: Headers) =>
  request<Conversation>(`/api/conversations/${id}`, headers)

export const startConversation = (messages: ChatMessage[], headers: Headers) =>
  request<ConversationSummary>("/api/conversations", headers, { messages })

export const addMessages = (
  id: string,
  messages: ChatMessage[],
  headers: Headers
) => request<void>(`/api/conversations/${id}/messages`, headers, { messages })
