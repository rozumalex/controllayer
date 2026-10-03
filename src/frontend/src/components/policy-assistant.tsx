import { ArrowRight, Sparkles } from "lucide-react"
import { useState } from "react"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Textarea } from "@/components/ui/textarea"
import { applyProposal, proposePolicy, type Proposal } from "@/lib/policy"

const roleName = (role: string) => (role === "*" ? "Default policy" : role)

// An admin writes a rule in plain language, a model proposes the changes,
// and nothing is saved until they apply them.
export function PolicyAssistant({ onApplied }: { onApplied: () => void }) {
  const [instruction, setInstruction] = useState("")
  const [proposal, setProposal] = useState<Proposal | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const run = async (action: () => Promise<void>) => {
    setBusy(true)
    setError(null)
    try {
      await action()
    } catch (error) {
      setError((error as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const propose = () =>
    run(async () => setProposal(await proposePolicy(instruction)))

  const apply = () =>
    run(async () => {
      if (!proposal) return
      await applyProposal(proposal)
      setProposal(null)
      setInstruction("")
      onApplied()
    })

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Sparkles className="size-4 text-primary" />
          Change policies in plain language
        </CardTitle>
        <p className="text-sm text-muted-foreground">
          A model proposes the changes. Nothing is saved until you apply them.
        </p>
      </CardHeader>
      <CardContent className="space-y-3">
        <Textarea
          placeholder="Analysts can't make payments and must see IBANs masked"
          value={instruction}
          maxLength={2000}
          onChange={(e) => setInstruction(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) propose()
          }}
        />
        <div className="flex items-center gap-3">
          <Button onClick={propose} disabled={busy || !instruction.trim()}>
            {busy && !proposal ? "Proposing…" : "Propose"}
          </Button>
          {error && <p className="text-sm text-destructive">{error}</p>}
        </div>

        {proposal && (
          <div className="space-y-3 rounded-lg border bg-muted/30 p-3">
            {proposal.roles.length === 0 && (
              <p className="text-sm text-muted-foreground">
                No change proposed.
              </p>
            )}
            {proposal.roles.map((role) => (
              <div key={role.role}>
                <p className="text-sm font-medium">{roleName(role.role)}</p>
                <ul className="mt-1 space-y-0.5 font-mono text-xs">
                  {role.changes.map((change) => (
                    <li
                      key={change.setting}
                      className="flex flex-wrap items-center gap-1.5"
                    >
                      <span className="text-muted-foreground">
                        {change.setting}
                      </span>
                      <span className="text-destructive line-through">
                        {change.before}
                      </span>
                      <ArrowRight className="size-3 text-muted-foreground" />
                      <span className="text-emerald-700 dark:text-emerald-400">
                        {change.after}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
            {proposal.dropped.length > 0 && (
              <div className="text-xs text-amber-700 dark:text-amber-400">
                <p className="font-medium">Left out, the policy can't hold:</p>
                <ul className="list-inside list-disc">
                  {proposal.dropped.map((item, i) => (
                    <li key={i}>{item}</li>
                  ))}
                </ul>
              </div>
            )}
            <div className="flex gap-2">
              <Button
                size="sm"
                onClick={apply}
                disabled={busy || proposal.roles.length === 0}
              >
                Apply
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={busy}
                onClick={() => setProposal(null)}
              >
                Discard
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
