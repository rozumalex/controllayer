import {
  AssistantRuntimeProvider,
  useLocalRuntime,
  type ChatModelAdapter,
} from "@assistant-ui/react"
import {
  Shield,
  ShieldBan,
  Lock,
  LockOpen,
  Play,
  RotateCcw,
  ShieldCheck,
  ShieldOff,
  SlidersHorizontal,
  Wallet,
} from "lucide-react"
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react"
import { CartesianGrid, Line, LineChart, XAxis, YAxis } from "recharts"

import { Thread } from "@/components/assistant-ui/elements/thread.aui"
import { Header, HeaderLink } from "@/components/brand"
import { SignOutButton } from "@/components/sign-in"
import { Greeting } from "@/components/chat"
import { ChatHistory } from "@/components/chat-history"
import { PolicySheet, type Editing } from "@/components/policy-sheet"
import {
  NoticeDialog,
  type Notice,
  type ScenarioNotice,
} from "@/components/simulator-notices"
import { OutcomeBadge } from "@/components/outcome"
import { TraceSheet } from "@/components/trace-sheet"
import { Avatar, AvatarBadge, AvatarFallback } from "@/components/ui/avatar"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart"
import { Checkbox } from "@/components/ui/checkbox"
import { ScrollArea } from "@/components/ui/scroll-area"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Separator } from "@/components/ui/separator"
import { Switch } from "@/components/ui/switch"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { TooltipProvider } from "@/components/ui/tooltip"
import { useChatHistory } from "@/hooks/use-chat-history"
import {
  formatDuration,
  formatNumber,
  formatTime,
  formatUsd,
} from "@/lib/format"
import { fetchTraces, type TraceList, type TraceSummary } from "@/lib/traces"
import { fetchPolicy, fetchTools } from "@/lib/policy"
import {
  chatCase,
  fetchCases,
  unlock,
  resetAccount,
  fetchSimulator,
  runAttack,
  advanceAttack,
  type Account,
  type CaseEvent,
  type CaseStatus,
  type EndEvent,
  type PromptEvent,
} from "@/lib/simulator"
import { initials } from "@/lib/users"
import { config, controlLayer } from "@/lib/assistant"
import { cn } from "@/lib/utils"

const STATUS: Record<CaseStatus, { label: string; style: string }> = {
  blocked: { label: "blocked", style: "text-destructive" },
  contained: { label: "redacted", style: "text-amber-700" },
  passed: { label: "got through", style: "text-amber-700" },
  landed: { label: "stolen", style: "text-destructive font-bold" },
  allowed: { label: "allowed", style: "text-emerald-700" },
  false_alarm: { label: "false alarm", style: "text-amber-700" },
  out_of_budget: { label: "out of budget", style: "text-orange-700" },
  locked_out: { label: "locked out", style: "text-orange-700" },
  unlocked: { label: "unlocked", style: "text-sky-700" },
}
// Each guard wears the color of the OWASP risk it mainly covers.
const GUARD_STYLES: Record<string, string> = {
  prompt_injection: "bg-violet-500/15 text-violet-700",
  semantic_injection: "bg-violet-500/15 text-violet-700",
  spotlight: "bg-violet-500/15 text-violet-700",
  sensitive_data: "bg-sky-500/15 text-sky-700",
  policy_clearance: "bg-sky-500/15 text-sky-700",
  data_flow: "bg-sky-500/15 text-sky-700",
  attack_signatures: "bg-red-500/15 text-red-700",
  policy_tools: "bg-slate-500/15 text-slate-700",
  policy_tools_listed: "bg-slate-500/15 text-slate-700",
  prompt_leak: "bg-fuchsia-500/15 text-fuchsia-700",
  policy_budget: "bg-orange-500/15 text-orange-700",
  rate_limit: "bg-orange-500/15 text-orange-700",
  loop: "bg-orange-500/15 text-orange-700",
  lockout: "bg-orange-500/15 text-orange-700",
  policy_model: "bg-orange-500/15 text-orange-700",
}
const TIMELINE = {
  blocked: { label: "Blocked", color: "#d03b3b" },
  allowed: { label: "Allowed", color: "#0ca30c" },
  missed: { label: "Missed", color: "#d97706" },
} satisfies ChartConfig
const USAGE = {
  usd: { label: "Spent", color: "#7c3aed" },
} satisfies ChartConfig
const LOGS = 40
const POINTS = 200
const fetchLogList = () => fetchTraces(LOGS)

// The name of the employee the chat acts as, for its greeting.
const Employee = createContext<string | undefined>(undefined)

function Welcome() {
  return <Greeting name={useContext(Employee)} />
}

// Polls fn every ms milliseconds, and at once when ms changes. Pass a
// function defined outside the component, so it stays the same.
function usePoll<T>(fn: () => Promise<T>, ms: number) {
  const [data, setData] = useState<T | null>(null)
  useEffect(() => {
    let current = true
    const load = () =>
      fn().then(
        (d) => current && setData(d),
        () => {}
      )
    void load()
    const timer = setInterval(load, ms)
    return () => {
      current = false
      clearInterval(timer)
    }
  }, [fn, ms])
  return data
}

// The session as a running count of each outcome, and of the dollars
// spent, from zero, at most POINTS points.
function timeline(feed: CaseEvent[]) {
  const totals = { blocked: 0, allowed: 0, missed: 0, usd: 0 }
  const points = [{ n: 0, ...totals }]
  feed.forEach((e, n) => {
    if (e.status === "unlocked") return
    // Missed: protection was off, and a guard would have stopped it.
    if (BLOCKED.includes(e.status)) totals.blocked++
    else if (!e.security && e.guard) totals.missed++
    else totals.allowed++
    totals.usd += Number(e.usd)
    points.push({ n: n + 1, ...totals })
  })
  const step = Math.ceil(points.length / POINTS)
  return points.filter((_, i) => i % step === 0 || i === points.length - 1)
}

function GuardPill({ guard }: { guard: string }) {
  return (
    <Badge
      variant="secondary"
      className={cn("font-mono", GUARD_STYLES[guard] ?? "bg-muted")}
    >
      {guard}
    </Badge>
  )
}

// The admin's own logs: the control layer's traces, as the dashboard shows
// them, newest first. A row opens the trace's timeline.
function Logs({
  traces,
  since,
  showPrevious,
  onShowPrevious,
  onHidePrevious,
}: {
  traces: TraceSummary[]
  // When set, hide traces from before this moment unless showPrevious.
  since: string | null
  showPrevious: boolean
  onShowPrevious: () => void
  onHidePrevious: () => void
}) {
  const [selected, setSelected] = useState<string | null>(null)
  const older = since ? traces.filter((trace) => trace.started_at < since) : []
  const visible =
    since && !showPrevious
      ? traces.filter((trace) => trace.started_at >= since)
      : traces

  if (!traces.length)
    return (
      <p className="py-6 text-center text-xs text-muted-foreground">
        Every request the guards check shows up here.
      </p>
    )

  return (
    <>
      {since && older.length > 0 && (
        <div className="mb-2">
          {showPrevious ? (
            <Button size="xs" variant="ghost" onClick={onHidePrevious}>
              Hide previous
            </Button>
          ) : (
            <Button size="xs" variant="ghost" onClick={onShowPrevious}>
              Show previous · {formatNumber(older.length)}
            </Button>
          )}
        </div>
      )}
      {!visible.length ? (
        <p className="py-6 text-center text-xs text-muted-foreground">
          New requests will show up here as you play.
        </p>
      ) : (
        <ol className="flex flex-col gap-1 text-xs">
          {visible.map((trace) => (
            <li key={trace.trace_id}>
              <button
                type="button"
                onClick={() => setSelected(trace.trace_id)}
                className="flex w-full flex-col gap-1 rounded-md border bg-card px-2 py-1.5 text-left hover:bg-muted"
              >
                <span className="flex items-center gap-2">
                  <OutcomeBadge outcome={trace.outcome} />
                  <span className="truncate font-medium">
                    {trace.user?.name ?? "no user"}
                  </span>
                  <span className="ml-auto shrink-0 text-muted-foreground tabular-nums">
                    {formatTime(trace.started_at)} ·{" "}
                    {formatNumber(trace.usage.total_tokens)} tokens ·{" "}
                    {formatDuration(trace.duration_ms)}
                  </span>
                </span>
                <span className="truncate text-muted-foreground">
                  {trace.prompt ?? "not stored"}
                </span>
                {trace.findings.length > 0 && (
                  <span className="flex flex-wrap gap-1">
                    {trace.findings.map((f, i) => (
                      <GuardPill key={i} guard={f.guard} />
                    ))}
                  </span>
                )}
              </button>
            </li>
          ))}
        </ol>
      )}
      <TraceSheet traceId={selected} onClose={() => setSelected(null)} />
    </>
  )
}

// Refreshes until the case's trace is in the log list, so the chat never
// paints a turn the Logs panel hasn't caught yet.
async function ensureLogged(
  traceId: string,
  refresh: () => Promise<TraceList | null>
) {
  for (let i = 0; i < 40; i++) {
    const list = await refresh()
    if (list?.traces.some((trace) => trace.trace_id === traceId)) return
    await new Promise((resolve) => setTimeout(resolve, 50))
  }
}

// The statuses of a case the control layer stopped.
const STOPPED: CaseStatus[] = ["blocked", "out_of_budget", "locked_out"]
// And of one it stopped, attack or not.
const BLOCKED: CaseStatus[] = [...STOPPED, "false_alarm"]

// Each finished chat answer, for the logs and the checklist.
type Answer = { text: string; traceId: string | null }
const answers = new EventTarget()

// Whose account the chat acts as, and whether the guards are on. The page
// sets it; the chat reads it on each request, so turning security on or off
// keeps the conversation.
const stolen = { role: "", security: true }

// A case answer waiting to be streamed into the chat instead of calling the
// model again. The adapter takes it on the next run, then falls through to
// the live control layer for typed prompts.
type ReplayAnswer = {
  text: string
  metadata: {
    custom: {
      blocked: boolean
      label: string
      story?: string
      owasp?: string
      title?: string
      verdict?: string
    }
  }
}
// The answer the next run of the chat streams, once it has come back.
type Replay = { answer: Promise<ReplayAnswer>; streamed: () => void }
const replayAnswer: { current: Replay | null } = { current: null }

// The answers of prompts already in the chat, by trace, until they come back.
type Pending = {
  resolve: (answer: ReplayAnswer) => void
  reject: (reason: Error) => void
  streamed: Promise<void>
}
const pending = new Map<string, Pending>()

// Ends the answers still waiting, as when the run is stopped.
function dropPending() {
  for (const p of pending.values()) p.reject(new Error("Stopped."))
  pending.clear()
}

const liveChat = controlLayer({
  headers: () => ({
    "X-Simulate-Role": stolen.role,
    "X-Simulate-Security": stolen.security ? "on" : "off",
  }),
  onAnswer: (text, traceId) =>
    answers.dispatchEvent(
      new CustomEvent<Answer>("answer", { detail: { text, traceId } })
    ),
})

const stolenChat: ChatModelAdapter = {
  async *run(options) {
    const replay = replayAnswer.current
    replayAnswer.current = null
    if (replay) {
      try {
        yield* streamReplay(await replay.answer, options.abortSignal)
      } catch {
        yield { content: [{ type: "text" as const, text: "Stopped." }] }
      } finally {
        replay.streamed()
      }
      return
    }
    const result = liveChat.run!(options)
    if (Symbol.asyncIterator in result) {
      yield* result
      return
    }
    yield await result
  },
}

// Paints an answer in a few frames, so it arrives like a live stream.
async function* streamReplay(
  { text, metadata }: ReplayAnswer,
  signal: AbortSignal
) {
  const step = Math.max(1, Math.ceil(text.length / 48))
  for (let end = step; end < text.length; end += step) {
    if (signal.aborted) return
    yield {
      content: [{ type: "text" as const, text: text.slice(0, end) }],
      metadata,
    }
    await new Promise((resolve) => setTimeout(resolve, 20))
  }
  yield { content: [{ type: "text" as const, text }], metadata }
}

const caseKey = (event: CaseEvent | PromptEvent) =>
  `${event.type}:${event.trace_id}:${event.id}`

type ChatThread = ReturnType<typeof useLocalRuntime>["thread"]

// What each kind of attack is, in words a jury reads at a glance.
const CATEGORIES: Record<string, string> = {
  benign: "Harmless request",
  obfuscation: "Hidden instructions",
  instruction_override: "Instruction override",
  jailbreak: "Jailbreak",
  indirect_injection: "Indirect injection",
  prompt_leak: "System prompt theft",
  exfiltration: "Data theft",
  secret_leak: "Secret leak",
  paraphrased: "Reworded injection",
  social_engineering: "Social engineering",
}
// The trick that disguises it.
const MUTATIONS: Record<string, string> = {
  base64: "Base64-encoded",
  hex: "hex-encoded",
  rot13: "ROT13-encoded",
  url_encode: "URL-encoded",
  reversed: "written backwards",
  leetspeak: "in leetspeak",
  homoglyph: "look-alike letters",
  zero_width: "invisible characters",
  mixed_case: "mixed case",
  spacing: "spaced out",
  payload_split: "split in two",
  upper: "in capitals",
  typo: "with typos",
  json: "inside JSON",
  markdown: "as a Markdown quote",
  code_fence: "in a code block",
  roleplay: "as role play",
  story: "as a story",
  polite: "asked politely",
  context: "with a cover story",
  email: "as an email",
  translate_pl: "in Polish",
  translate_de: "in German",
  translate_es: "in Spanish",
}

// What the case is, shown above its prompt.
function caseLabel(
  event: Pick<
    CaseEvent,
    "scenario" | "owasp" | "title" | "turn" | "turns" | "mutation" | "category"
  >
) {
  if (event.scenario && event.owasp && event.title && event.turn && event.turns)
    return `Attack: ${event.owasp} · ${event.title} · ${event.turn} of ${event.turns}`
  const trick = MUTATIONS[event.mutation]
  if (event.category === "benign")
    return `Normal request${trick ? `: ${trick}` : ""}`
  const kind = CATEGORIES[event.category] ?? event.category
  return `Attack: ${trick ? `${kind} · ${trick}` : kind}`
}

// A clear refusal in the model's own words. It only says the model refused
// when it said so, so the label never claims more than the answer shows.
const REFUSAL =
  /\bI(?: cannot| can't| can not| won't| will not| am unable to|'m unable to| must decline)\b/i

// What came of it, shown above its answer.
function answerLabel(event: CaseEvent) {
  if (event.status === "landed")
    return `Portcullis: ${event.stolen} items stolen`
  const refused = REFUSAL.test(event.answer)
  if (!event.security && event.guard)
    return refused
      ? "Portcullis: protection off · the model refused on its own"
      : `Portcullis: protection off · ${event.guard} would have blocked it`
  if (event.status === "passed")
    return refused
      ? "Portcullis: not stopped · the model refused on its own"
      : "Portcullis: not stopped · nothing stolen"
  if (event.status === "locked_out") return "Portcullis: account locked out"
  if (event.status === "out_of_budget") return "Portcullis: budget spent"
  if (event.status === "false_alarm")
    return `Portcullis: blocked by ${event.guard ?? "a guard"} · a false alarm`
  if (!event.guard)
    return `Portcullis: ${STATUS[event.status]?.label ?? event.status}`
  return `Portcullis: ${STATUS[event.status]?.label ?? event.status} by ${event.guard}`
}

// What the chat streams for a case: the answer that already came back from
// the attack run (no second model call).
function answerOf(event: CaseEvent): ReplayAnswer {
  return {
    text: event.answer || event.reason || "No answer.",
    metadata: {
      custom: {
        blocked: BLOCKED.includes(event.status),
        label: answerLabel(event),
        ...(event.story && event.owasp && event.title && event.verdict
          ? {
              story: event.story,
              owasp: event.owasp,
              title: event.title,
              verdict: event.verdict,
            }
          : {}),
      },
    },
  }
}

// Shows a prompt in the chat at once. Its answer waits in pending until the
// case comes back.
async function ask(thread: ChatThread, event: CaseEvent | PromptEvent) {
  const kind =
    event.type === "prompt"
      ? { ...event, category: "scenario", mutation: "none" }
      : event
  let streamed = () => {}
  const done = new Promise<void>((resolve) => (streamed = resolve))
  const answer = new Promise<ReplayAnswer>((resolve, reject) =>
    pending.set(event.trace_id, { resolve, reject, streamed: done })
  )
  // Shown as rejected only when the stolenChat run awaits it.
  answer.catch(() => {})
  replayAnswer.current = { answer, streamed }
  await thread.append({
    role: "user",
    content: [{ type: "text", text: event.prompt }],
    metadata: {
      custom: {
        label: caseLabel(kind),
        tone: kind.category === "benign" ? "normal" : "attack",
      },
    },
    // Runs stolenChat, which streams the answer into the assistant turn.
    startRun: true,
  })
}

// Streams a case's answer under its prompt, which ask put in the chat, and
// waits until it's painted.
async function answer(event: CaseEvent) {
  const waiting = pending.get(event.trace_id)
  if (!waiting) return
  pending.delete(event.trace_id)
  waiting.resolve(answerOf(event))
  await waiting.streamed
}

// The bank's chat as the employee whose account was stolen, just as on the
// main page. The cases of an attack show in it as they run: each prompt, and
// the answer that came back, in red when the control layer stopped it.
function StolenChat({
  role,
  cases,
  wait,
  pauseForNext,
  played,
  ensureLog,
  locked,
}: {
  role: string
  cases: (CaseEvent | PromptEvent)[]
  wait: () => Promise<void>
  // After a scenario's last turn: show Next and wait for a click.
  pauseForNext: (event: CaseEvent) => Promise<void>
  // Called once each case has played, so a notice shows with its case.
  played: (event: CaseEvent) => void
  // Wait until the case is visible in Logs before painting the chat turn.
  ensureLog: (traceId: string) => Promise<void>
  // Why the chat takes no prompts, or nothing when it does.
  locked?: string
}) {
  const runtime = useLocalRuntime(stolenChat)
  // The chat's own auto-scroll follows a model's run, not messages added
  // without one, so each played case scrolls it to the bottom here.
  const box = useRef<HTMLDivElement>(null)
  const follow = () => {
    const viewport = box.current?.querySelector(
      "[data-slot=aui_thread-viewport]"
    )
    viewport?.scrollTo({ top: viewport.scrollHeight })
  }
  const history = useChatHistory(runtime, { "X-Simulate-Role": role })
  // The cases already there when the chat opens, as when you switch
  // accounts, aren't played again.
  const [shown] = useState(() => new Set(cases.map(caseKey)))
  // The cases still to play, one after another.
  const playing = useRef(Promise.resolve())

  useEffect(() => {
    for (const event of cases) {
      const key = caseKey(event)
      if (shown.has(key)) continue
      shown.add(key)
      playing.current = playing.current.then(async () => {
        // The prompt shows as soon as it's sent, and a case without one
        // shows its own.
        if (event.type === "prompt" || !pending.has(event.trace_id)) {
          await wait()
          // A new scenario starts a fresh thread, once earlier ones have
          // already put messages in it.
          if (event.turn === 1 && runtime.thread.getState().messages.length > 0)
            await runtime.thread.reset()
          await ask(runtime.thread, event)
          requestAnimationFrame(follow)
        }
        if (event.type === "prompt") return
        await ensureLog(event.trace_id)
        await answer(event)
        requestAnimationFrame(follow)
        played(event)
        // Hold here (not before the next case): a click during streaming
        // can't clear the gate early and let the following scenario through.
        await pauseForNext(event)
      })
    }
  }, [cases, runtime, shown, wait, pauseForNext, played, ensureLog])

  return (
    <AssistantRuntimeProvider runtime={runtime} config={config}>
      <ChatHistory history={history} onNew={() => runtime.thread.reset()}>
        <div ref={box} className="contents">
          <Thread components={{ Welcome }} disabled={locked} autoScroll />
        </div>
      </ChatHistory>
    </AssistantRuntimeProvider>
  )
}

// Says, over the chat, when the layer has cut the account off, so it shows
// after its notice is closed.
function AccountBanner({
  account,
  security,
  onUnlock,
}: {
  account: Account
  security: boolean
  onUnlock: () => void
}) {
  if (account.locked)
    return (
      <div className="flex items-center gap-2 rounded-t-xl border-b border-destructive/30 bg-destructive/10 px-3 py-2 text-sm font-semibold text-destructive">
        <Lock className="size-4 shrink-0" />
        Account locked by Portcullis: {account.lock_reason}.
        <Button
          size="sm"
          variant="destructive"
          className="ml-auto shrink-0"
          onClick={onUnlock}
        >
          <LockOpen /> Unblock
        </Button>
      </div>
    )
  const budget = formatUsd(Number(account.policy.budget.weekly_usd))
  if (account.out_of_budget)
    return (
      <div className="flex items-center gap-2 rounded-t-xl border-b border-orange-400/40 bg-orange-100 px-3 py-2 text-sm font-semibold text-orange-800 dark:bg-orange-500/15 dark:text-orange-300">
        <Wallet className="size-4 shrink-0" />
        {security
          ? `Account limited by Portcullis: it spent its ${budget} for the week, so the model takes no more of its prompts until Monday.`
          : `Over budget: it spent its ${budget} for the week. With protection off, Portcullis only watches, so its prompts still reach the model.`}
      </div>
    )
  return null
}

const ROLE_KEY = "simulator.role"

export function Simulator() {
  // Often, as it says which accounts the layer locked out.
  const setup = usePoll(fetchSimulator, 3000)
  const tools = usePoll(fetchTools, 60_000)
  const polledLogs = usePoll(fetchLogList, 2000)
  const [traceList, setTraceList] = useState<TraceList | null>(null)
  // ensureLog may find a trace before the next poll; keep the fresher list.
  const logs = traceList ?? polledLogs
  const refreshTraces = useCallback(async () => {
    try {
      const list = await fetchLogList()
      setTraceList(list)
      return list
    } catch {
      return null
    }
  }, [])
  const ensureLog = useCallback(
    (traceId: string) => ensureLogged(traceId, refreshTraces),
    [refreshTraces]
  )
  // The account picked last, so a reload keeps it and its chat history.
  const [chosen, choose] = useState<string | null>(() => {
    try {
      return localStorage.getItem(ROLE_KEY)
    } catch {
      return null
    }
  })
  const setRole = (role: string) => {
    choose(role)
    try {
      localStorage.setItem(ROLE_KEY, role)
    } catch {
      // Without storage, a reload goes back to the default account.
    }
  }
  const [security, setSecurity] = useState(true)
  const [achieved, setAchieved] = useState(new Set<string>())
  // Every case of the session, chat answers too, oldest first.
  const [feed, setFeed] = useState<CaseEvent[]>([])
  // The cases of the current or last run.
  const [run, setRun] = useState<(CaseEvent | PromptEvent)[]>([])
  const [notices, setNotices] = useState<Notice[]>([{ kind: "welcome" }])
  // After Start hacking: hide traces from before this moment.
  const [since, setSince] = useState<string | null>(null)
  const [showPrevious, setShowPrevious] = useState(false)
  // Bumped on Start hacking so an in-flight reload of past cases is ignored.
  const boot = useRef(0)
  const [error, setError] = useState<string | null>(null)
  const [abort, setAbort] = useState<AbortController | null>(null)
  // After a scenario's last turn: wait for Explain or Next before the next
  // one plays. Keeps the run controls up until the user advances.
  const gate = useRef<{ promise: Promise<void>; done: () => void } | null>(null)
  const [waiting, setWaiting] = useState(false)
  // The scenarios of this run that have played to their last turn.
  const [finished, setFinished] = useState(0)
  const running = abort !== null || waiting
  const runId = useRef<string | null>(null)
  const waitNext = () => {
    if (gate.current) return
    let done = () => {}
    const promise = new Promise<void>((resolve) => (done = resolve))
    gate.current = { promise, done }
    setWaiting(true)
  }
  const goNext = () => {
    if (!gate.current) return
    gate.current.done()
    gate.current = null
    setWaiting(false)
    // Drop a story dialog still open, so it doesn't sit over the next case.
    setNotices((notices) => notices.filter((n) => n.kind !== "scenario"))
    const id = runId.current
    if (id) void advanceAttack(id, security)
  }
  // While a notice is open the attack pauses: paused() resolves once it's
  // closed.
  const resume = useRef<{ promise: Promise<void>; done: () => void } | null>(
    null
  )
  // Pauses at once, not after the next render, so no case after the one
  // that opened the notice gets through.
  const pause = () => {
    if (resume.current) return
    let done = () => {}
    const promise = new Promise<void>((resolve) => (done = resolve))
    resume.current = { promise, done }
  }
  useEffect(() => {
    if (notices.length) pause()
    else if (resume.current) {
      resume.current.done()
      resume.current = null
    }
  }, [notices.length])
  const chatPaused = useCallback(async () => {
    // Notices and the scenario Next gate both hold the chat and the stream,
    // so charts and logs stay with the message.
    while (resume.current || gate.current)
      await (resume.current ?? gate.current)?.promise
  }, [])
  // After a scenario's last turn has streamed: show Next and don't start the
  // next case until it's clicked.
  const pauseForNext = useCallback(
    async (event: CaseEvent) => {
      const last =
        Boolean(event.verdict) ||
        (event.turn != null &&
          event.turns != null &&
          event.turn === event.turns)
      if (!last) return
      setFinished((n) => n + 1)
      waitNext()
      await chatPaused()
    },
    [chatPaused]
  )

  // The notices this run has shown, so each shows once.
  const shown = useRef(new Set<string>())

  const accounts = setup?.accounts ?? []
  const role =
    accounts.find((a) => a.role === chosen)?.role ??
    accounts.find((a) => a.role === "Analyst")?.role ??
    accounts[0]?.role
  const account = accounts.find((a) => a.role === role)
  const lockout = account?.policy.lockout
  const checklist = setup?.checklist ?? []
  const ticked = checklist.filter((item) => achieved.has(item.id)).length

  const notify = (notice: Notice, once?: string) => {
    if (once && shown.current.has(once)) return
    if (once) shown.current.add(once)
    pause()
    setNotices((notices) => [...notices, notice])
  }

  const lockedOut = () => {
    if (!lockout) return
    notify(
      {
        kind: "locked_out",
        blocks: lockout.blocks,
        minutes: lockout.minutes,
      },
      "locked"
    )
  }

  // The chat is locked by the blocked attack that reaches the limit, not by
  // the lockout guard, so tell the attacker when the account turns locked.
  // An attack tells it when its cases have played.
  const wasLocked = useRef<{ role?: string; locked?: boolean }>({})
  useEffect(() => {
    const locked = account?.locked
    const before = wasLocked.current
    if (locked && !running && before.role === role && before.locked === false)
      lockedOut()
    if (before.role === role && before.locked && !locked)
      shown.current.delete("locked")
    wasLocked.current = { role, locked }
  })

  // Ticks the checklist, and tells the attacker what just happened.
  function took(event: CaseEvent, chat: boolean) {
    const fresh = event.achieved.filter((goal) => !achieved.has(goal))
    if (fresh.length) {
      setAchieved((achieved) => new Set([...achieved, ...fresh]))
      for (const id of fresh) {
        const title = setup?.checklist.find((item) => item.id === id)?.title
        if (chat && title) notify({ kind: "achieved", goal: title })
      }
    }
    if (event.stolen && !chat)
      notify({ kind: "breach", stolen: event.stolen, security }, "breach")
    if (event.guard === "lockout") lockedOut()
  }

  function ended(event: EndEvent) {
    if (event.outcome === "locked_out") lockedOut()
    if (event.outcome === "out_of_budget") notify({ kind: "out_of_budget" })
    if (event.outcome === "done")
      notify({
        kind: "done",
        blocked: event.blocked,
        cases: event.cases,
        stolen: event.stolen,
      })
  }

  async function answered(text: string, traceId: string | null) {
    if (!traceId) return
    try {
      const event = await chatCase(traceId, text, security)
      setFeed((feed) => [...feed, event])
      took(event, true)
    } catch (error) {
      setError((error as Error).message)
    }
  }

  // The account's logs, kept on the server: the charts, the logs and the
  // checklist come back on a reload, and change with the account.
  useEffect(() => {
    if (!role) return
    const n = boot.current
    let current = true
    fetchCases(role).then(
      (cases) => {
        if (!current) return
        // Charts always keep history.
        setFeed(cases)
        // After Start hacking, don't put past checklist ticks back.
        if (boot.current !== n) return
        setAchieved(new Set(cases.flatMap((c) => c.achieved)))
      },
      (error: Error) => current && boot.current === n && setError(error.message)
    )
    return () => {
      current = false
    }
  }, [role])

  // Start hacking: wipe the checklist and hide earlier logs for a clean demo.
  // Charts keep the full history.
  async function startHacking() {
    const n = ++boot.current
    setShowPrevious(false)
    setSince(new Date().toISOString())
    setAchieved(new Set())
    setRun([])
    setNotices((notices) => notices.slice(1))
    if (!role) return
    try {
      await resetAccount(role)
    } catch (error) {
      if (boot.current === n) setError((error as Error).message)
    }
  }

  useEffect(() => {
    stolen.role = role ?? ""
    stolen.security = security
  }, [role, security])

  useEffect(() => {
    const listen = (event: Event) => {
      const { text, traceId } = (event as CustomEvent<Answer>).detail
      void answered(text, traceId)
    }
    answers.addEventListener("answer", listen)
    return () => answers.removeEventListener("answer", listen)
  })

  useEffect(() => {
    window.dispatchEvent(
      new CustomEvent("portcullis-waiting", { detail: waiting })
    )
  }, [waiting])

  useEffect(() => {
    const explain = (event: Event) => {
      const detail = (event as CustomEvent<ScenarioNotice>).detail
      if (!detail?.story) return
      setNotices((notices) => [...notices, { kind: "scenario", ...detail }])
    }
    const next = () => goNext()
    window.addEventListener("portcullis-explain", explain)
    window.addEventListener("portcullis-next", next)
    return () => {
      window.removeEventListener("portcullis-explain", explain)
      window.removeEventListener("portcullis-next", next)
    }
  })

  // Starts the account's checklist over, for the next demo. The charts and
  // logs keep every case.
  async function reset(role: string) {
    try {
      await resetAccount(role)
      setAchieved(new Set())
    } catch (error) {
      setError((error as Error).message)
    }
  }

  async function unlocked(role: string) {
    try {
      const event = await unlock(role)
      setFeed((feed) => [...feed, event])
    } catch (error) {
      setError((error as Error).message)
    }
  }

  // The cases of the run the chat has yet to play, and its end, which waits
  // for them, so each notice shows with the prompt that caused it.
  const unplayed = useRef(0)
  const end = useRef<EndEvent | null>(null)
  const onPlayed = useRef<(event: CaseEvent) => void>(() => {})
  useEffect(() => {
    onPlayed.current = (event) => {
      setFeed((feed) => [...feed, event])
      took(event, false)
      unplayed.current -= 1
      if (unplayed.current === 0 && end.current) {
        const finish = end.current
        end.current = null
        void chatPaused().then(() => ended(finish))
      }
    }
  })
  const played = useCallback((event: CaseEvent) => onPlayed.current(event), [])

  async function attack() {
    if (!role || !setup) return
    const controller = new AbortController()
    setAbort(controller)
    dropPending()
    setRun([])
    setError(null)
    shown.current = new Set()
    unplayed.current = 0
    end.current = null
    gate.current?.done()
    gate.current = null
    setWaiting(false)
    runId.current = null
    setFinished(0)
    try {
      await runAttack(
        { role, goals: setup.goals.map((g) => g.id), security },
        (event) => {
          if ("run_id" in event && event.run_id) runId.current = event.run_id
          if (event.type === "end") {
            if (unplayed.current) {
              end.current = event
              return
            }
            end.current = event
            void chatPaused().then(() => {
              if (end.current !== event) return
              end.current = null
              ended(event)
            })
            return
          }
          if (event.type === "case") unplayed.current += 1
          setRun((run) => [...run, event])
        },
        controller.signal,
        chatPaused
      )
    } catch (error) {
      if (!controller.signal.aborted) setError((error as Error).message)
    } finally {
      setAbort(null)
      // Only release on abort: a finished stream still waits for Next on the
      // last scenario before the done notice.
      if (controller.signal.aborted) {
        dropPending()
        goNext()
      }
    }
  }

  // The account's policy, in the editor of the Controls tab.
  const [editing, setEditing] = useState<Editing | null>(null)
  async function manage() {
    try {
      const overview = await fetchPolicy()
      const found = overview.roles.find((r) => r.role === role)
      setEditing(
        found
          ? { role: found.role, policy: found }
          : { role: null, policy: overview.default }
      )
    } catch (error) {
      setError((error as Error).message)
    }
  }

  const points = timeline(feed)
  const spent = points[points.length - 1]
  const scenarios = setup?.scenarios ?? 0
  const missing = setup?.missing ?? []

  return (
    <TooltipProvider>
      <div className="flex h-svh flex-col bg-muted/40">
        <NoticeDialog
          notice={notices[0] ?? null}
          checklist={checklist}
          onClose={() => {
            const closed = notices[0]
            if (!closed) return
            if (closed.kind === "welcome") {
              void startHacking()
              return
            }
            // Explain / other notices only dismiss. Next is the Next button.
            setNotices((current) =>
              closed.kind === "scenario"
                ? current.filter((n) => n.kind !== "scenario")
                : current[0] === closed
                  ? current.slice(1)
                  : current
            )
          }}
        />
        <Header product="Attack simulator">
          <label
            className={cn(
              "flex cursor-pointer items-center gap-2 rounded-full border px-2.5 py-1 text-xs",
              security
                ? "border-emerald-400/40 bg-emerald-400/10 text-emerald-300"
                : "border-red-400/50 bg-red-500/20 text-red-200"
            )}
          >
            {security ? (
              <ShieldCheck className="size-3.5" />
            ) : (
              <ShieldOff className="size-3.5" />
            )}
            <span className="hidden sm:inline">
              {security
                ? "Protected by AI control layer"
                : "AI control layer protection disabled"}
            </span>
            <Switch
              size="sm"
              checked={security}
              disabled={running && !waiting}
              onCheckedChange={setSecurity}
              className="data-[state=checked]:bg-emerald-400 data-[state=unchecked]:bg-red-400"
            />
          </label>
          <Select value={role ?? ""} onValueChange={setRole} disabled={running}>
            <SelectTrigger
              title="The account you stole"
              className="h-9 border-0 bg-transparent text-primary-foreground shadow-none hover:bg-primary-foreground/10 focus-visible:ring-0 *:data-[slot=select-value]:overflow-visible! dark:bg-transparent [&>svg:last-child]:hidden"
            >
              <SelectValue placeholder="…" />
            </SelectTrigger>
            <SelectContent>
              {accounts.map((a) => (
                <SelectItem key={a.role} value={a.role}>
                  <Avatar size="sm">
                    <AvatarFallback className="bg-gold text-primary">
                      {initials(a.name)}
                    </AvatarFallback>
                    {a.locked && (
                      <AvatarBadge
                        title="Locked out"
                        className="bg-destructive text-white group-data-[size=sm]/avatar:size-3.5 group-data-[size=sm]/avatar:[&>svg]:block group-data-[size=sm]/avatar:[&>svg]:size-2.5"
                      >
                        <ShieldBan />
                      </AvatarBadge>
                    )}
                  </Avatar>
                  <span className="text-sm">{a.name}</span>
                  <span className="text-xs opacity-70">{a.role}</span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            size="sm"
            variant="ghost"
            className="text-primary-foreground hover:bg-primary-foreground/10 hover:text-primary-foreground"
            disabled={!role || running}
            onClick={() => void manage()}
          >
            <SlidersHorizontal /> Manage
          </Button>
          <HeaderLink href="/admin" label="Admin" icon={Shield} />
          <SignOutButton />
        </Header>
        <PolicySheet
          key={editing ? (editing.role ?? "default") : "closed"}
          editing={editing}
          tools={tools}
          onClose={() => setEditing(null)}
          onSaved={() => setEditing(null)}
        />

        <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-auto p-3 lg:overflow-hidden">
          <main className="grid min-h-0 flex-1 gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)_minmax(0,1.2fr)]">
            {/* You, the attacker: the account, the checklist, the button. */}
            <Card size="sm" className="min-h-0">
              <ScrollArea className="min-h-0 flex-1">
                <CardContent className="flex flex-col gap-3">
                  <div className="flex flex-col gap-2">
                    <p className="flex items-center justify-between gap-2 font-semibold">
                      Hacker's checklist
                      <span className="ml-auto text-muted-foreground tabular-nums">
                        {ticked} / {checklist.length}
                      </span>
                      <Button
                        size="xs"
                        variant="ghost"
                        disabled={running || !role}
                        onClick={() => role && void reset(role)}
                      >
                        <RotateCcw /> Reset
                      </Button>
                    </p>
                    {checklist.map((g) => (
                      <div key={g.id} className="flex items-start gap-2">
                        <Checkbox
                          className="pointer-events-none mt-0.5 data-[state=checked]:border-destructive data-[state=checked]:bg-destructive"
                          checked={achieved.has(g.id)}
                          tabIndex={-1}
                          aria-readonly
                        />
                        <span>
                          <span
                            className={cn(
                              "block font-medium",
                              achieved.has(g.id) &&
                                "text-destructive line-through"
                            )}
                          >
                            {g.title}
                          </span>
                          <span className="block text-xs text-muted-foreground">
                            {g.description}
                          </span>
                        </span>
                      </div>
                    ))}
                  </div>

                  {running ? (
                    // Waits for the attack playing now to finish.
                    <Button size="lg" disabled={!waiting} onClick={goNext}>
                      {finished < scenarios ? (
                        <>
                          <Play /> Next attack ·{" "}
                          <span className="tabular-nums">
                            {formatNumber(finished + 1)} /{" "}
                            {formatNumber(scenarios)}
                          </span>
                        </>
                      ) : (
                        "See the results"
                      )}
                    </Button>
                  ) : (
                    <>
                      <Button
                        size="lg"
                        variant="destructive"
                        disabled={
                          !account || account.locked || missing.length > 0
                        }
                        onClick={() => void attack()}
                      >
                        <Play /> Run attack scenario
                        <span className="font-normal tabular-nums opacity-80">
                          · 1 / {formatNumber(scenarios)}
                        </span>
                      </Button>
                      {missing.length > 0 && (
                        <p className="text-xs text-muted-foreground">
                          Still to fill: {missing.join(", ")}
                        </p>
                      )}
                    </>
                  )}
                  {error && <p className="text-xs text-destructive">{error}</p>}
                </CardContent>
              </ScrollArea>
            </Card>

            {/* The bank's chat, as the employee whose account you stole. */}
            <Card size="sm" className="min-h-0 gap-0 py-0">
              {account && role && (
                <AccountBanner
                  account={account}
                  security={security}
                  onUnlock={() => void unlocked(role)}
                />
              )}
              <Employee.Provider value={account?.name}>
                {role && (
                  <StolenChat
                    key={role}
                    role={role}
                    cases={run}
                    wait={chatPaused}
                    pauseForNext={pauseForNext}
                    played={played}
                    ensureLog={ensureLog}
                    locked={
                      account?.locked
                        ? "This account is locked out."
                        : undefined
                    }
                  />
                )}
              </Employee.Provider>
            </Card>

            {/* The bank's side: the dashboard, live, and the logs. */}
            <Card size="sm" className="min-h-0 min-w-0 overflow-hidden">
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  Live admin dashboard
                  <span className="size-2 animate-pulse rounded-full bg-emerald-500" />
                </CardTitle>
              </CardHeader>
              <CardContent className="flex min-h-0 flex-1 flex-col gap-3">
                <Tabs defaultValue="requests" className="shrink-0">
                  <TabsList>
                    <TabsTrigger value="requests">Requests</TabsTrigger>
                    <TabsTrigger value="usage">Spend</TabsTrigger>
                  </TabsList>
                  <TabsContent value="requests">
                    <ChartContainer
                      config={TIMELINE}
                      className="aspect-auto h-40 w-full"
                    >
                      <LineChart data={points}>
                        <CartesianGrid vertical={false} />
                        <XAxis dataKey="n" tickLine={false} axisLine={false} />
                        <YAxis
                          tickLine={false}
                          axisLine={false}
                          width={32}
                          allowDecimals={false}
                        />
                        <ChartTooltip content={<ChartTooltipContent />} />
                        <ChartLegend content={<ChartLegendContent />} />
                        {(
                          Object.keys(TIMELINE) as (keyof typeof TIMELINE)[]
                        ).map((key) => (
                          <Line
                            key={key}
                            dataKey={key}
                            type="monotone"
                            isAnimationActive={false}
                            stroke={`var(--color-${key})`}
                            strokeWidth={2}
                            dot={false}
                          />
                        ))}
                      </LineChart>
                    </ChartContainer>
                  </TabsContent>
                  <TabsContent value="usage">
                    <p className="text-sm tabular-nums">
                      <span className="font-semibold">
                        {formatUsd(spent.usd)}
                      </span>{" "}
                      spent
                    </p>
                    <ChartContainer
                      config={USAGE}
                      className="aspect-auto h-36 w-full"
                    >
                      <LineChart data={points}>
                        <CartesianGrid vertical={false} />
                        <XAxis dataKey="n" tickLine={false} axisLine={false} />
                        <YAxis
                          tickLine={false}
                          axisLine={false}
                          width={48}
                          tickFormatter={formatUsd}
                        />
                        <ChartTooltip content={<ChartTooltipContent />} />
                        <Line
                          dataKey="usd"
                          type="monotone"
                          isAnimationActive={false}
                          stroke="var(--color-usd)"
                          strokeWidth={2}
                          dot={false}
                        />
                      </LineChart>
                    </ChartContainer>
                  </TabsContent>
                </Tabs>
                <Separator />
                <p className="text-xs font-semibold text-muted-foreground">
                  Logs
                </p>
                <ScrollArea className="min-h-0 min-w-0 flex-1 [&_[data-slot=scroll-area-viewport]>div]:!block">
                  <Logs
                    traces={logs?.traces ?? []}
                    since={since}
                    showPrevious={showPrevious}
                    onShowPrevious={() => setShowPrevious(true)}
                    onHidePrevious={() => setShowPrevious(false)}
                  />
                </ScrollArea>
              </CardContent>
            </Card>
          </main>
        </div>
      </div>
    </TooltipProvider>
  )
}
