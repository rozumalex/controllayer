import { useState, type ReactNode } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { Slider } from "@/components/ui/slider"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import {
  CLEARANCES,
  TOOL_ACTIONS,
  resetPolicy,
  savePolicy,
  type GatewayTool,
  type PolicyRead,
  type PolicySettings,
  type ToolAction,
} from "@/lib/policy"
import { cn } from "@/lib/utils"

// What the sheet edits: the default policy (role null) or a role's.
export type Editing = { role: string | null; policy: PolicyRead }

const ACTION_COLORS: Record<ToolAction, string> = {
  allow: "data-[state=on]:bg-emerald-100 data-[state=on]:text-emerald-800",
  redact: "data-[state=on]:bg-amber-100 data-[state=on]:text-amber-800",
  block: "data-[state=on]:bg-destructive/15 data-[state=on]:text-destructive",
}

function ActionPicker({
  value,
  onChange,
  actions = TOOL_ACTIONS,
  label,
}: {
  value: ToolAction
  onChange: (action: ToolAction) => void
  actions?: readonly ToolAction[]
  label: string
}) {
  return (
    <ToggleGroup
      type="single"
      variant="outline"
      size="sm"
      aria-label={label}
      value={value}
      // Radix sends "" when the chosen item is clicked again; keep the value.
      onValueChange={(action) => action && onChange(action as ToolAction)}
    >
      {actions.map((action) => (
        <ToggleGroupItem
          key={action}
          value={action}
          className={cn("px-2.5 capitalize", ACTION_COLORS[action])}
        >
          {action}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
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

// An empty input is no limit.
const toNumber = (value: string) => (value === "" ? null : Number(value))

export function PolicySheet({
  editing,
  models,
  tools,
  onClose,
  onSaved,
}: {
  editing: Editing | null
  models: string[]
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
          <SheetTitle>{role ?? "Default policy"}</SheetTitle>
          <SheetDescription>
            {role
              ? editing?.policy.customized
                ? "This role has its own policy."
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
                <div className="flex flex-wrap items-center gap-3">
                  <Select
                    value={draft.clearance}
                    onValueChange={(clearance) =>
                      update({ clearance: clearance as typeof draft.clearance })
                    }
                  >
                    <SelectTrigger className="w-40">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {CLEARANCES.map((c) => (
                        <SelectItem key={c} value={c}>
                          {c}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <span className="text-sm text-muted-foreground">
                    more sensitive:
                  </span>
                  <ActionPicker
                    label="Data above the clearance"
                    actions={["redact", "block"]}
                    value={draft.above_clearance}
                    onChange={(above_clearance) => update({ above_clearance })}
                  />
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
              <h3 className="font-medium">Models and budget</h3>
              <Field label="Allowed models">
                <div className="grid grid-cols-2 gap-2">
                  {models.map((model) => (
                    <label
                      key={model}
                      className="flex items-center gap-2 text-sm"
                    >
                      <Checkbox
                        checked={draft.allowed_models.includes(model)}
                        onCheckedChange={(checked) =>
                          update({
                            allowed_models: checked
                              ? [...draft.allowed_models, model]
                              : draft.allowed_models.filter((m) => m !== model),
                          })
                        }
                      />
                      <span className="font-mono text-xs">{model}</span>
                    </label>
                  ))}
                </div>
              </Field>
              <div className="grid grid-cols-2 gap-4">
                <Field
                  label="Tokens a month"
                  hint="Per employee; empty is none"
                >
                  <Input
                    type="number"
                    min={0}
                    step={1000}
                    placeholder="Unlimited"
                    value={draft.budget.monthly_tokens ?? ""}
                    onChange={(e) =>
                      update({
                        budget: {
                          ...draft.budget,
                          monthly_tokens: toNumber(e.target.value),
                        },
                      })
                    }
                  />
                </Field>
                <Field label="USD a month" hint="Per employee; empty is none">
                  <Input
                    type="number"
                    min={0}
                    step="0.01"
                    placeholder="Unlimited"
                    value={draft.budget.monthly_usd ?? ""}
                    onChange={(e) =>
                      update({
                        budget: {
                          ...draft.budget,
                          monthly_usd: e.target.value || null,
                        },
                      })
                    }
                  />
                </Field>
              </div>
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
