import { Download } from "lucide-react"
import { useState } from "react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { downloadTraces, type ExportFormat, type Outcome } from "@/lib/traces"

const PERIODS = {
  "1h": { label: "Last hour", ms: 60 * 60 * 1000 },
  "24h": { label: "Last 24 hours", ms: 24 * 60 * 60 * 1000 },
  "7d": { label: "Last 7 days", ms: 7 * 24 * 60 * 60 * 1000 },
  "30d": { label: "Last 30 days", ms: 30 * 24 * 60 * 60 * 1000 },
  all: { label: "All time", ms: null },
} as const

type Period = keyof typeof PERIODS

const OUTCOMES: Outcome[] = ["allowed", "flagged", "blocked", "error"]

// The guards' names, see the name of each guard in app/control/guards.
const GUARDS = [
  "prompt_injection",
  "semantic_injection",
  "sensitive_data",
  "spotlight",
  "policy_model",
  "policy_budget",
  "policy_tools",
  "policy_clearance",
]
const ANY_GUARD = "any"

export function ExportDialog() {
  const [open, setOpen] = useState(false)
  const [format, setFormat] = useState<ExportFormat>("csv")
  const [period, setPeriod] = useState<Period>("24h")
  const [outcomes, setOutcomes] = useState<Outcome[]>([])
  const [guard, setGuard] = useState(ANY_GUARD)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function download() {
    setBusy(true)
    setError(null)
    try {
      const ms = PERIODS[period].ms
      await downloadTraces({
        format,
        start: ms === null ? undefined : new Date(Date.now() - ms),
        outcomes,
        guard: guard === ANY_GUARD ? undefined : guard,
      })
      setOpen(false)
    } catch (error) {
      setError((error as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          <Download />
          Export
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Export the audit log</DialogTitle>
          <DialogDescription>
            One row per request, with its user, outcome, findings and tokens.
            Prompts are in it only when the layer stores them.
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4">
          <div className="grid gap-2">
            <Label>Period</Label>
            <Select
              value={period}
              onValueChange={(value) => setPeriod(value as Period)}
            >
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {Object.entries(PERIODS).map(([value, { label }]) => (
                  <SelectItem key={value} value={value}>
                    {label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="grid gap-2">
            <Label>Outcome</Label>
            <ToggleGroup
              type="multiple"
              variant="outline"
              size="sm"
              aria-label="Outcome"
              value={outcomes}
              onValueChange={(value) => setOutcomes(value as Outcome[])}
            >
              {OUTCOMES.map((outcome) => (
                <ToggleGroupItem
                  key={outcome}
                  value={outcome}
                  className="px-2.5 capitalize"
                >
                  {outcome}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
            <p className="text-xs text-muted-foreground">
              None picked exports every outcome.
            </p>
          </div>

          <div className="grid gap-2">
            <Label>Guard with a finding</Label>
            <Select value={guard} onValueChange={setGuard}>
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ANY_GUARD}>Any or none</SelectItem>
                {GUARDS.map((name) => (
                  <SelectItem key={name} value={name}>
                    {name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="grid gap-2">
            <Label>Format</Label>
            <ToggleGroup
              type="single"
              variant="outline"
              size="sm"
              aria-label="Format"
              value={format}
              // Radix sends "" when the chosen item is clicked again; keep it.
              onValueChange={(value) =>
                value && setFormat(value as ExportFormat)
              }
            >
              <ToggleGroupItem value="csv" className="px-3">
                CSV
              </ToggleGroupItem>
              <ToggleGroupItem value="json" className="px-3">
                JSON
              </ToggleGroupItem>
            </ToggleGroup>
          </div>

          {error && <p className="text-sm text-destructive">{error}</p>}
        </div>

        <DialogFooter>
          <DialogClose asChild>
            <Button variant="outline">Cancel</Button>
          </DialogClose>
          <Button onClick={() => void download()} disabled={busy}>
            <Download />
            {busy ? "Exporting…" : "Download"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
