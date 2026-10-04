import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import type { Outcome } from "@/lib/traces"

const STYLES: Record<Outcome, string> = {
  allowed: "bg-emerald-500/10 text-emerald-700",
  suspicious: "bg-yellow-400/20 text-yellow-800",
  flagged: "bg-amber-500/15 text-amber-700",
  blocked: "bg-destructive/10 text-destructive",
  error: "bg-muted text-muted-foreground",
  unlocked: "bg-sky-500/15 text-sky-700",
}

export function OutcomeBadge({ outcome }: { outcome: Outcome }) {
  return (
    <Badge variant="secondary" className={cn("capitalize", STYLES[outcome])}>
      {outcome}
    </Badge>
  )
}
