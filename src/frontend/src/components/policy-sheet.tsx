import { useState, type ReactNode } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { Slider } from "@/components/ui/slider"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import {
  CLEARANCES,
  PII,
  TOOL_ACTIONS,
  piiAction,
  resetPolicy,
  savePolicy,
  type Clearance,
  type GatewayTool,
  type PolicyRead,
  type PolicySettings,
  type ToolAction,
} from "@/lib/policy"
import { cn } from "@/lib/utils"

// What the sheet edits: the default policy (role null) or a role's.
export type Editing = { role: string | null; policy: PolicyRead }

const ACTION_COLORS: Record<ToolAction, string> = {
  allow:
    "data-[state=active]:bg-emerald-100 data-[state=active]:text-emerald-800",
  redact: "data-[state=active]:bg-amber-100 data-[state=active]:text-amber-800",
  block:
    "data-[state=active]:bg-destructive/15 data-[state=active]:text-destructive",
}

// Picks one of the actions, as tabs.
function ActionPicker({
  value,
  onChange,
  actions = TOOL_ACTIONS,
  names = {},
  label,
}: {
  value: ToolAction
  onChange: (action: ToolAction) => void
  actions?: readonly ToolAction[]
  // What each action is called here, when its name alone isn't clear.
  names?: Partial<Record<ToolAction, string>>
  label: string
}) {
  return (
    <Tabs
      value={value}
      onValueChange={(action) => onChange(action as ToolAction)}
      className="shrink-0"
    >
      <TabsList aria-label={label} className="h-8">
        {actions.map((action) => (
          <TabsTrigger
            key={action}
            value={action}
            className={cn("px-2.5 text-xs capitalize", ACTION_COLORS[action])}
          >
            {names[action] ?? action}
          </TabsTrigger>
        ))}
      </TabsList>
    </Tabs>
  )
}

// Four stops, from public to restricted.
function ClearanceSlider({
  value,
  onChange,
}: {
  value: Clearance
  onChange: (clearance: Clearance) => void
}) {
  const index = CLEARANCES.indexOf(value)
  return (
    <div className="flex w-64 flex-col gap-2">
      <div>
        <Slider
          aria-label="Data clearance"
          min={0}
          max={CLEARANCES.length - 1}
          step={1}
          value={[index]}
          onValueChange={([i]) => onChange(CLEARANCES[i])}
        />
      </div>
      <div className="flex justify-between text-xs text-muted-foreground">
        {CLEARANCES.map((c) => (
          <span
            key={c}
            className={cn(c === value && "font-medium text-foreground")}
          >
            {c.toLowerCase()}
          </span>
        ))}
      </div>
    </div>
  )
}

function Field({
  label,
  hint,
  children,
}: {
  label: string
  hint?: string
  children: ReactNode
}) {
  return (
    <div className="flex flex-col gap-2">
      <Label>{label}</Label>
      {children}
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  )
}

export function PolicySheet({
  editing,
  tools,
  onClose,
  onSaved,
}: {
  editing: Editing | null
  tools: GatewayTool[] | null
  onClose: () => void
  onSaved: () => void
}) {
  // The page remounts the sheet for each policy it opens, so the draft
  // starts from that policy.
  const [draft, setDraft] = useState<PolicySettings | null>(
    () => editing && structuredClone(editing.policy.settings)
  )
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const update = (change: Partial<PolicySettings>) =>
    setDraft((draft) => draft && { ...draft, ...change })

  async function run(action: () => Promise<unknown>) {
    setBusy(true)
    setError(null)
    try {
      await action()
      onSaved()
      onClose()
    } catch (error) {
      setError((error as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const role = editing?.role ?? null
  // Tools a saved policy names but no server serves any more stay listed, so
  // they can be removed.
  const toolNames = [
    ...new Set([
      ...(tools ?? []).map((t) => t.name),
      ...Object.keys(draft?.tools ?? {}),
    ]),
  ].sort()
  const toolInfo = new Map((tools ?? []).map((t) => [t.name, t]))

  return (
    <Sheet open={editing !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-full gap-0 sm:max-w-xl">
        <SheetHeader className="border-b">
          <div className="flex items-center gap-2">
            <SheetTitle>{role ?? "Default policy"}</SheetTitle>
          </div>
          <SheetDescription>
            {role
              ? editing?.policy.customized
                ? "Role Policy"
                : "This role follows the default policy. Saving gives it its own."
              : "Every role without a policy of its own follows this one."}
          </SheetDescription>
        </SheetHeader>

        {draft && (
          <div className="flex flex-1 flex-col gap-6 overflow-y-auto p-4">
            <section className="flex flex-col gap-4">
              <h3 className="font-medium">Data and guards</h3>
              <Field
                label="Data clearance"
                hint="The most sensitive fields of the bank's data catalog the role sees as they are."
              >
                <ClearanceSlider
                  value={draft.clearance}
                  onChange={(clearance) => update({ clearance })}
                />
              </Field>
              <Field
                label="Data above the clearance"
                hint={
                  draft.above_clearance === "redact"
                    ? "The answer comes back with those fields masked."
                    : "The whole request is refused."
                }
              >
                <ActionPicker
                  label="Data above the clearance"
                  actions={["redact", "block"]}
                  names={{
                    redact: "Mask the fields",
                    block: "Refuse the request",
                  }}
                  value={draft.above_clearance}
                  onChange={(above_clearance) => update({ above_clearance })}
                />
              </Field>
              <Field
                label="PII in free text"
                hint="Found by pattern in prompts, notes and tool results, before the model sees them. Each kind has a sensitivity; until you pick an action, it follows the clearance like catalog data. Secrets are always blocked."
              >
                <div className="grid grid-cols-[auto_1fr] items-center gap-x-4 gap-y-2">
                  {PII.map(({ kind, label, level }) => (
                    <div key={kind} className="contents">
                      <span className="flex flex-col text-sm">
                        {label}
                        <span className="text-xs text-muted-foreground">
                          {level.toLowerCase()} data
                          {draft.pii[kind] ? "" : ", follows the clearance"}
                        </span>
                      </span>
                      <ActionPicker
                        label={label}
                        value={piiAction(draft, kind, level)}
                        onChange={(action) =>
                          update({ pii: { ...draft.pii, [kind]: action } })
                        }
                      />
                    </div>
                  ))}
                </div>
              </Field>
              <Field
                label={`Prompt injection threshold: ${draft.injection_threshold.toFixed(2)}`}
                hint="A score at or above it blocks. Lower is stricter."
              >
                <Slider
                  min={0}
                  max={1}
                  step={0.05}
                  value={[draft.injection_threshold]}
                  onValueChange={([injection_threshold]) =>
                    update({ injection_threshold })
                  }
                />
              </Field>
            </section>

            <section className="flex flex-col gap-4">
              <h3 className="font-medium">Budget and lockout</h3>
              <div className="grid grid-cols-2 gap-4">
                <Field label="USD a week">
                  <Input
                    type="number"
                    min={0}
                    step="0.01"
                    placeholder="Unlimited"
                    value={draft.budget.weekly_usd ?? ""}
                    onChange={(e) =>
                      update({
                        budget: {
                          ...draft.budget,
                          weekly_usd: e.target.value || null,
                        },
                      })
                    }
                  />
                </Field>
              </div>
              <Field
                label="Lockout"
                hint="Too many blocked attacks or suspicious requests in a short time is someone probing the guards, often with a stolen account. A request is suspicious when an injection guard scored it high but let it through. Budget, rate limit and loop blocks don't count, nor do poisoned tool results, which block the tool instead. 0 turns a count off."
              >
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  Lock after
                  <Input
                    type="number"
                    min={0}
                    className="w-20"
                    aria-label="Blocked attacks"
                    value={draft.lockout.blocks}
                    onChange={(e) =>
                      update({
                        lockout: {
                          ...draft.lockout,
                          blocks: Number(e.target.value),
                        },
                      })
                    }
                  />
                  blocked attacks or
                  <Input
                    type="number"
                    min={0}
                    className="w-20"
                    aria-label="Suspicious requests"
                    value={draft.lockout.flags}
                    onChange={(e) =>
                      update({
                        lockout: {
                          ...draft.lockout,
                          flags: Number(e.target.value),
                        },
                      })
                    }
                  />
                  suspicious requests in
                  <Input
                    type="number"
                    min={1}
                    className="w-20"
                    aria-label="Minutes"
                    value={draft.lockout.minutes}
                    onChange={(e) =>
                      update({
                        lockout: {
                          ...draft.lockout,
                          minutes: Number(e.target.value),
                        },
                      })
                    }
                  />
                  minutes
                </div>
              </Field>
            </section>

            <section className="flex flex-col gap-3">
              <div className="flex items-center justify-between gap-3">
                <h3 className="font-medium">Tools</h3>
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  Any other tool
                  <ActionPicker
                    label="Any other tool"
                    value={draft.default_tool_action}
                    onChange={(default_tool_action) =>
                      update({ default_tool_action })
                    }
                  />
                </div>
              </div>
              {tools === null && (
                <p className="text-sm text-muted-foreground">
                  Loading the gateway tools…
                </p>
              )}
              {tools?.length === 0 && toolNames.length === 0 && (
                <p className="text-sm text-muted-foreground">
                  No MCP server is enabled, so the gateway has no tools.
                </p>
              )}
              <ul className="divide-y rounded-lg border">
                {toolNames.map((name) => {
                  const info = toolInfo.get(name)
                  const action = draft.tools[name] ?? draft.default_tool_action
                  return (
                    <li
                      key={name}
                      className="flex items-center justify-between gap-3 px-3 py-2"
                    >
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="truncate font-mono text-xs">
                            {name}
                          </span>
                          {info?.destructive ? (
                            <Badge variant="destructive">destructive</Badge>
                          ) : info?.read_only ? (
                            <Badge variant="secondary">read</Badge>
                          ) : info ? (
                            <Badge variant="outline">write</Badge>
                          ) : (
                            <Badge variant="outline">not served</Badge>
                          )}
                        </div>
                        {info?.description && (
                          <p className="truncate text-xs text-muted-foreground">
                            {info.description}
                          </p>
                        )}
                      </div>
                      <ActionPicker
                        label={name}
                        value={action}
                        onChange={(action) =>
                          update({ tools: { ...draft.tools, [name]: action } })
                        }
                      />
                    </li>
                  )
                })}
              </ul>
            </section>
          </div>
        )}

        <SheetFooter className="border-t sm:flex-row sm:justify-between">
          {error && (
            <p className="text-sm text-destructive sm:basis-full">{error}</p>
          )}
          <Button
            variant="ghost"
            disabled={busy || !editing?.policy.customized}
            onClick={() => run(() => resetPolicy(role))}
          >
            {role ? "Follow the default" : "Reset to the environment"}
          </Button>
          <Button
            disabled={busy || !draft}
            onClick={() => draft && run(() => savePolicy(role, draft))}
          >
            Save policy
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  )
}
