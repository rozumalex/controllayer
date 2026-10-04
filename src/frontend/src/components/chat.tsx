import { Logo } from "@/components/brand"

function greeting() {
  const hour = new Date().getHours()
  if (hour < 12) return "Good morning"
  if (hour < 18) return "Good afternoon"
  return "Good evening"
}

// The chat's greeting, by the user's first name.
export function Greeting({ name }: { name?: string }) {
  const firstName = name?.split(" ")[0]
  return (
    <div className="mb-6 flex animate-in flex-col gap-3 px-2 duration-200 fill-mode-both fade-in slide-in-from-bottom-1">
      <Logo className="size-12" />
      <h1 className="font-serif text-3xl font-semibold tracking-tight text-primary">
        {greeting()}
        {firstName && `, ${firstName}`}.
      </h1>
      <p className="text-muted-foreground">
        Ask about markets, clients or internal policy.
      </p>
    </div>
  )
}
