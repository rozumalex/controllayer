import { useEffect, useId, useState, type ReactNode } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Label } from "@/components/ui/label"
import { Slider } from "@/components/ui/slider"
import { Switch } from "@/components/ui/switch"
import {
  fetchControls,
  resetControl,
  saveControl,
  type Direction,
  type GuardControl,
  type GuardSettings,
  type Mode,
} from "@/lib/controls"
import { cn } from "@/lib/utils"

const DIRECTIONS: Record<Direction, string> = {
  inbound: "Prompts and tool calls",
  outbound: "Tool results",
}

const MODES: { value: Mode; label: string; detail: string }[] = [
  { value: "enforce", label: "Enforce", detail: "Blocks what it catches." },
  {
    value: "monitor",
    label: "Monitor",
    detail: "Logs what it catches as flagged and lets it through.",
  },
]

const ruleName = (name: string) =>
  name.replaceAll("_", " ").replace(/^./, (c) => c.toUpperCase())

function same(a: GuardSettings, b: GuardSettings) {
  const sorted = (s: GuardSettings) => ({
    ...s,
    directions: [...s.directions].sort(),
    disabled_rules: [...s.disabled_rules].sort(),
  })
  return JSON.stringify(sorted(a)) === JSON.stringify(sorted(b))
}

function toggle<T>(list: T[], item: T, on: boolean) {
  return on ? [...list, item] : list.filter((x) => x !== item)
}

function Section({
  title,
  className,
  children,
}: {
  title: string
  className?: string
  children: ReactNode
}) {
  return (
    <section className={cn("flex flex-col gap-3", className)}>
      <h3 className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
        {title}
      </h3>
      {children}
    </section>
  )
}

function GuardCard({
  control,
  onChange,
}: {
  control: GuardControl
  onChange: (control: GuardControl) => void
}) {
  const id = useId()
  const [draft, setDraft] = useState(control.settings)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  const dirty = !same(draft, control.settings)
  const update = (changes: Partial<GuardSettings>) => {
    setDraft((draft) => ({ ...draft, ...changes }))
    setSaved(false)
  }

  async function run(action: () => Promise<GuardControl>) {
    setBusy(true)
    setError(null)
    try {
      const control = await action()
      onChange(control)
      setDraft(control.settings)
      setSaved(true)
    } catch (error) {
      setError((error as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const threshold = draft.threshold ?? 0

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-4">
          <div className="flex flex-col gap-1.5">
            <CardTitle className="flex items-center gap-2">
              {control.title}
              <Badge variant={control.customized ? "secondary" : "outline"}>
                {control.customized ? "Custom" : "Default"}
              </Badge>
            </CardTitle>
            <CardDescription>{control.description}</CardDescription>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <Label htmlFor={`${id}-enabled`} className="text-muted-foreground">
              {draft.enabled ? "On" : "Off"}
            </Label>
            <Switch
              id={`${id}-enabled`}
              checked={draft.enabled}
              onCheckedChange={(enabled) => update({ enabled })}
            />
          </div>
        </div>
      </CardHeader>

      <CardContent
        className={cn(
          "grid gap-6 transition-opacity md:grid-cols-2",
          !draft.enabled && "pointer-events-none opacity-50"
        )}
      >
        {control.blocks && (
          <Section title="Mode">
            <div className="inline-flex w-fit rounded-lg bg-muted p-[3px]">
              {MODES.map(({ value, label }) => (
                <Button
                  key={value}
                  size="sm"
                  variant={draft.mode === value ? "outline" : "ghost"}
                  className={cn(draft.mode !== value && "border-transparent")}
                  onClick={() => update({ mode: value })}
                >
                  {label}
                </Button>
              ))}
            </div>
            <p className="text-sm text-muted-foreground">
              {MODES.find((m) => m.value === draft.mode)?.detail}
            </p>
          </Section>
        )}

        <Section title="Checks">
          {control.directions.map((direction) => (
            <div key={direction} className="flex items-center gap-2">
              <Checkbox
                id={`${id}-${direction}`}
                checked={draft.directions.includes(direction)}
                disabled={control.directions.length === 1}
                onCheckedChange={(on) =>
                  update({
                    directions: toggle(
                      draft.directions,
                      direction,
                      on === true
                    ),
                  })
                }
              />
              <Label htmlFor={`${id}-${direction}`} className="font-normal">
                {DIRECTIONS[direction]}
                <span className="text-muted-foreground">({direction})</span>
              </Label>
            </div>
          ))}
        </Section>

        {control.scored && (
          <Section title="Threshold">
            <div className="flex items-center gap-4">
              <Slider
                min={0.05}
                max={1}
                step={0.05}
                value={[threshold]}
                onValueChange={([threshold]) => update({ threshold })}
                aria-label="Threshold"
              />
              <span className="w-10 text-right font-medium tabular-nums">
                {threshold.toFixed(2)}
              </span>
            </div>
            <p className="text-sm text-muted-foreground">
              A message that scores {threshold.toFixed(2)} or more is caught.
              Rules that score less only show up in the logs.
            </p>
          </Section>
        )}

        {control.rules.length > 0 && (
          <Section title="Rules" className="md:col-span-2">
            <ul className="flex flex-col divide-y rounded-lg border">
              {control.rules.map((rule) => {
                const on = !draft.disabled_rules.includes(rule.name)
                const catches = rule.score >= threshold
                return (
                  <li
                    key={rule.name}
                    className="flex items-center gap-3 px-3 py-2"
                  >
                    <Switch
                      size="sm"
                      id={`${id}-${rule.name}`}
                      checked={on}
                      onCheckedChange={(on) =>
                        update({
                          disabled_rules: toggle(
                            draft.disabled_rules,
                            rule.name,
                            !on
                          ),
                        })
                      }
                    />
                    <Label
                      htmlFor={`${id}-${rule.name}`}
                      className="flex min-w-0 flex-1 flex-col items-start gap-0.5"
                    >
                      <span>{ruleName(rule.name)}</span>
                      <span className="font-normal text-muted-foreground">
                        {rule.description}
                      </span>
                    </Label>
                    <Badge
                      variant="secondary"
                      className={cn(
                        "tabular-nums",
                        on && catches && "bg-destructive/10 text-destructive"
                      )}
                      title={catches ? "Caught" : "Below the threshold"}
                    >
                      {rule.score.toFixed(2)}
                    </Badge>
                  </li>
                )
              })}
            </ul>
          </Section>
        )}
      </CardContent>

      <CardFooter className="flex items-center justify-end gap-2">
        <p className="mr-auto text-sm">
          {error ? (
            <span className="text-destructive">{error}</span>
          ) : dirty ? (
            <span className="text-muted-foreground">Unsaved changes</span>
          ) : (
            saved && (
              <span className="text-emerald-700">
                Saved. The next request uses it.
              </span>
            )
          )}
        </p>
        {control.customized && (
          <Button
            variant="ghost"
            size="sm"
            disabled={busy}
            onClick={() => run(() => resetControl(control.name))}
          >
            Reset to defaults
          </Button>
        )}
        {dirty && (
          <Button
            variant="outline"
            size="sm"
            disabled={busy}
            onClick={() => setDraft(control.settings)}
          >
            Discard
          </Button>
        )}
        <Button
          size="sm"
          disabled={!dirty || busy}
          onClick={() => run(() => saveControl(control.name, draft))}
        >
          Save
        </Button>
      </CardFooter>
    </Card>
  )
}

export function Controls() {
  const [controls, setControls] = useState<GuardControl[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchControls()
      .then(setControls)
      .catch((error: Error) => setError(error.message))
  }, [])

  const replace = (control: GuardControl) =>
    setControls(
      (controls) =>
        controls?.map((c) => (c.name === control.name ? control : c)) ?? null
    )

  if (error)
    return (
      <p className="text-sm text-destructive">
        Could not load the controls: {error}
      </p>
    )
  if (!controls)
    return <p className="text-sm text-muted-foreground">Loading…</p>

  return (
    <div className="flex flex-col gap-4">
      {controls.map((control) => (
        <GuardCard key={control.name} control={control} onChange={replace} />
      ))}
    </div>
  )
}
