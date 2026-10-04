import { AssistantRuntimeProvider, useLocalRuntime } from "@assistant-ui/react"
import {
  ShieldBan,
  Bot,
  ChevronRight,
  CircleHelp,
  Code,
  Database,
  FileLock,
  FlaskConical,
  Gauge,
  Package,
  Play,
  ScrollText,
  ShieldCheck,
  ShieldOff,
  SlidersHorizontal,
  Square,
  Syringe,
  type LucideIcon,
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
import { Header } from "@/components/brand"
import { Greeting } from "@/components/chat"
import { ChatHistory } from "@/components/chat-history"
import { PolicySheet, type Editing } from "@/components/policy-sheet"
import { NoticeDialog, type Notice } from "@/components/simulator-notices"
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
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
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
import { formatNumber, formatUsd } from "@/lib/format"
import { fetchPolicy, fetchTools } from "@/lib/policy"
import {
  chatCase,
  fetchCases,
  unlock,
  fetchSimulator,
  runAttack,
  type CaseEvent,
  type CaseStatus,
  type EndEvent,
  type Risk,
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
  prompt_leak: "bg-fuchsia-500/15 text-fuchsia-700",
  policy_budget: "bg-orange-500/15 text-orange-700",
  rate_limit: "bg-orange-500/15 text-orange-700",
  loop: "bg-orange-500/15 text-orange-700",
  lockout: "bg-orange-500/15 text-orange-700",
  policy_model: "bg-orange-500/15 text-orange-700",
}
const ICONS: Record<string, LucideIcon> = {
  LLM01: Syringe,
  LLM02: FileLock,
  LLM03: Package,
  LLM04: FlaskConical,
  LLM05: Code,
  LLM06: Bot,
  LLM07: ScrollText,
  LLM08: Database,
  LLM09: CircleHelp,
  LLM10: Gauge,
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
// spent, from zero, at most POINTS
// points.
function timeline(feed: CaseEvent[]) {
  const totals = { blocked: 0, allowed: 0, missed: 0, usd: 0 }
  const points = [{ n: 0, ...totals }]
  feed.forEach((e, n) => {
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

// The attacks the layer stopped, by OWASP risk. Each counts once, under the
// risk the server gave it.
function Owasp({ risks, feed }: { risks: Risk[]; feed: CaseEvent[] }) {
  return (
    <div className="grid shrink-0 grid-cols-5 gap-2 lg:grid-cols-10">
      {risks.map((risk) => {
        const guards = risk.guards
        const Icon = ICONS[risk.id]
        const hits = feed.filter((e) => e.risk === risk.id).length
        return (
          <Card
            key={risk.id}
            size="sm"
            title={`OWASP ${risk.id}: ${guards.join(", ") || "not covered"}`}
            className={cn(
              "transition-colors",
              !guards.length && "opacity-50",
              hits > 0 && "bg-emerald-500/10 ring-emerald-500"
            )}
          >
            <CardContent className="flex flex-col gap-1">
              <span className="flex items-center justify-between">
                <Icon
                  className={cn(
                    "size-5",
                    hits > 0 ? "text-emerald-700" : "text-muted-foreground"
                  )}
                />
                <span
                  className={cn(
                    "text-base leading-none font-semibold tabular-nums",
                    hits > 0 ? "text-emerald-700" : "text-muted-foreground"
                  )}
                >
                  {guards.length ? hits : "—"}
                </span>
              </span>
              <span className="text-xs leading-tight font-medium">
                {risk.title}
              </span>
            </CardContent>
          </Card>
        )
      })}
    </div>
  )
}

// One group per request, newest first, with its guards in the order they ran.
function Logs({ feed }: { feed: CaseEvent[] }) {
  if (!feed.length)
    return (
      <p className="py-6 text-center text-xs text-muted-foreground">
        Every request the guards check shows up here.
      </p>
    )
  return (
    <ol className="flex flex-col gap-2 font-mono text-[11px]">
      {feed
        .slice(-LOGS)
        .reverse()
        .map((e) => {
          const ms = e.verdicts.reduce((sum, v) => sum + v.latency_ms, 0)
          return (
            <li key={e.trace_id}>
              <Card size="sm" className="gap-0 py-0 font-mono text-[11px]">
                <Collapsible>
                  <CollapsibleTrigger className="group flex w-full items-center gap-2 bg-muted/60 px-2 py-1 text-left hover:bg-muted">
                    <ChevronRight className="size-3 shrink-0 transition-transform group-data-[state=open]:rotate-90" />
                    <span
                      className={cn("font-semibold", STATUS[e.status].style)}
                    >
                      {STATUS[e.status].label}
                      {e.stolen > 0 && ` +${e.stolen}`}
                    </span>
                    <span className="truncate">{e.id}</span>
                    <span className="ml-auto shrink-0 text-muted-foreground">
                      {e.trace_id.slice(0, 6)} · {e.verdicts.length} checks ·{" "}
                      {ms.toFixed(1)}ms
                    </span>
                  </CollapsibleTrigger>
                  <CollapsibleContent>
                    <Separator />
                    <ol className="px-2 py-0.5">
                      {e.verdicts.map((v, i) => (
                        <li
                          key={i}
                          className="flex items-center gap-1.5 py-0.5"
                        >
                          <span
                            className={cn(
                              "w-11 shrink-0",
                              v.action === "allow" && "text-emerald-700",
                              v.action === "block" && "text-destructive",
                              v.action === "modify" && "text-amber-700"
                            )}
                          >
                            {v.action}
                          </span>
                          <GuardPill guard={v.guard} />
                          <span className="shrink-0 text-muted-foreground">
                            {v.direction} {v.tool} {v.latency_ms.toFixed(1)}ms
                          </span>
                          <span className="truncate">{v.reason}</span>
                        </li>
                      ))}
                    </ol>
                  </CollapsibleContent>
                </Collapsible>
              </Card>
            </li>
          )
        })}
    </ol>
  )
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

const stolenChat = controlLayer({
  headers: () => ({
    "X-Simulate-Role": stolen.role,
    "X-Simulate-Security": stolen.security ? "on" : "off",
  }),
  onAnswer: (text, traceId) =>
    answers.dispatchEvent(
      new CustomEvent<Answer>("answer", { detail: { text, traceId } })
    ),
})

// How long typing a prompt into the chat takes, and in how many steps.
const TYPING_MS = 700
const TYPING_STEPS = 20
// How long a stopped answer stays before the next case starts a new chat.
const STOPPED_MS = 600
// With more cases than this waiting, the chat shows them without typing.
const BACKLOG = 5

const caseKey = (event: CaseEvent) => `${event.trace_id}:${event.id}`

type ChatThread = ReturnType<typeof useLocalRuntime>["thread"]

const sleep = (ms: number) => new Promise((done) => setTimeout(done, ms))

// Types the case's prompt into the chat's composer, sends it, and shows what
// came back, as if the attacker typed it, only fast. The case already ran on
// the server, so sending it only shows it. The more cases wait, the faster it
// types, so the chat keeps up with the run.
async function replay(thread: ChatThread, event: CaseEvent, waiting: number) {
  const composer = thread.composer
  if (waiting <= BACKLOG) {
    const pause = TYPING_MS / TYPING_STEPS / (1 + waiting)
    const step = Math.ceil(event.prompt.length / TYPING_STEPS)
    for (let end = step; end < event.prompt.length; end += step) {
      composer.setText(event.prompt.slice(0, end))
      await sleep(pause)
    }
  }
  composer.setText("")
  await thread.append({
    role: "user",
    content: [{ type: "text", text: event.prompt }],
    startRun: false,
  })
  await thread.append({
    role: "assistant",
    content: [
      { type: "text", text: event.answer || event.reason || "No answer." },
    ],
    metadata: { custom: { blocked: STOPPED.includes(event.status) } },
    startRun: false,
  })
}

// The bank's chat as the employee whose account was stolen, just as on the
// main page. The cases of an attack play in it as they run: the attacker
// types each prompt and sends it, and the answer comes back, in red when the
// control layer stopped it. After a stopped case, the next starts a new chat.
function StolenChat({
  role,
  cases,
  wait,
  locked,
}: {
  role: string
  cases: CaseEvent[]
  wait: () => Promise<void>
  locked: boolean
}) {
  const runtime = useLocalRuntime(stolenChat)
  // The employee's own chat history.
  const history = useChatHistory(runtime, { "X-Simulate-Role": role })
  // The cases already there when the chat opens, as when you switch
  // accounts, aren't played again.
  const [shown] = useState(() => new Set(cases.map(caseKey)))
  // The cases still to play, one after another.
  const playing = useRef(Promise.resolve())
  const waiting = useRef(0)
  const stopped = useRef(false)

  useEffect(() => {
    for (const event of cases) {
      const key = caseKey(event)
      if (shown.has(key)) continue
      shown.add(key)
      waiting.current += 1
      playing.current = playing.current.then(async () => {
        await wait()
        waiting.current -= 1
        if (stopped.current) {
          if (waiting.current <= BACKLOG) await sleep(STOPPED_MS)
          runtime.thread.reset()
        }
        await replay(runtime.thread, event, waiting.current)
        stopped.current = STOPPED.includes(event.status)
      })
    }
  }, [cases, runtime, shown, wait])

  return (
    <AssistantRuntimeProvider runtime={runtime} config={config}>
      <ChatHistory history={history} onNew={() => runtime.thread.reset()}>
        <Thread
          components={{ Welcome }}
          disabled={locked ? "This account is locked out." : undefined}
        />
      </ChatHistory>
    </AssistantRuntimeProvider>
  )
}

const ROLE_KEY = "simulator.role"

export function Simulator() {
  // Often, as it says which accounts the layer locked out.
  const setup = usePoll(fetchSimulator, 3000)
  const tools = usePoll(fetchTools, 60_000)
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
  const [run, setRun] = useState<CaseEvent[]>([])
  const [notices, setNotices] = useState<Notice[]>([{ kind: "welcome" }])
  const [error, setError] = useState<string | null>(null)
  const [abort, setAbort] = useState<AbortController | null>(null)
  const running = abort !== null
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
  const paused = useCallback(
    () => resume.current?.promise ?? Promise.resolve(),
    []
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
  // The items this account can tick: one cleared for everything can't read
  // above its clearance.
  const checklist =
    setup?.checklist.filter((item) => account?.checklist.includes(item.id)) ??
    []
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
    let current = true
    fetchCases(role).then(
      (cases) => {
        if (!current) return
        setFeed(cases)
        setAchieved(new Set(cases.flatMap((c) => c.achieved)))
      },
      (error: Error) => current && setError(error.message)
    )
    return () => {
      current = false
    }
  }, [role])

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

  async function attack() {
    if (!role || !setup) return
    const controller = new AbortController()
    setAbort(controller)
    setRun([])
    setError(null)
    shown.current = new Set()
    try {
      await runAttack(
        { role, goals: setup.goals.map((g) => g.id), security },
        (event) => {
          if (event.type === "end") return ended(event)
          setRun((run) => [...run, event])
          setFeed((feed) => [...feed, event])
          took(event, false)
        },
        controller.signal,
        paused
      )
    } catch (error) {
      if (!controller.signal.aborted) setError((error as Error).message)
    } finally {
      setAbort(null)
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
  const cases = setup?.goals.reduce((sum, g) => sum + g.cases, 0) ?? 0

  return (
    <TooltipProvider>
      <div className="flex h-svh flex-col bg-muted/40">
        <NoticeDialog
          notice={notices[0] ?? null}
          checklist={checklist}
          onClose={() => setNotices((notices) => notices.slice(1))}
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
              disabled={running}
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
        </Header>
        <PolicySheet
          key={editing ? (editing.role ?? "default") : "closed"}
          editing={editing}
          tools={tools}
          onClose={() => setEditing(null)}
          onSaved={() => setEditing(null)}
          onUnlock={account?.locked && role ? () => unlock(role) : undefined}
        />

        <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-auto p-3 lg:overflow-hidden">
          <Owasp risks={setup?.risks ?? []} feed={feed} />

          <main className="grid min-h-0 flex-1 gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)_minmax(0,1.2fr)]">
            {/* You, the attacker: the account, the checklist, the button. */}
            <Card size="sm" className="min-h-0">
              <ScrollArea className="min-h-0 flex-1">
                <CardContent className="flex flex-col gap-3">
                  <div className="flex flex-col gap-2">
                    <p className="flex justify-between font-semibold">
                      Hacker's checklist
                      <span className="text-muted-foreground tabular-nums">
                        {ticked} / {checklist.length}
                      </span>
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
                    <Button
                      size="lg"
                      variant="outline"
                      onClick={() => abort.abort()}
                    >
                      <Square /> Stop
                    </Button>
                  ) : (
                    <Button
                      size="lg"
                      variant="destructive"
                      disabled={!account}
                      onClick={() => void attack()}
                    >
                      <Play /> Attack with {formatNumber(cases)} prompts
                    </Button>
                  )}
                  {error && <p className="text-xs text-destructive">{error}</p>}
                </CardContent>
              </ScrollArea>
            </Card>

            {/* The bank's chat, as the employee whose account you stole. */}
            <Card size="sm" className="min-h-0 py-0">
              <Employee.Provider value={account?.name}>
                {role && (
                  <StolenChat
                    key={role}
                    role={role}
                    cases={run}
                    wait={paused}
                    locked={account?.locked ?? false}
                  />
                )}
              </Employee.Provider>
            </Card>

            {/* The bank's side: the dashboard, live, and the logs. */}
            <Card size="sm" className="min-h-0">
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
                <ScrollArea className="min-h-0 flex-1">
                  <Logs feed={feed} />
                </ScrollArea>
              </CardContent>
            </Card>
          </main>
        </div>
      </div>
    </TooltipProvider>
  )
}
