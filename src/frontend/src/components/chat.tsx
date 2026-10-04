import { AssistantRuntimeProvider, useLocalRuntime } from "@assistant-ui/react"
import { Shield, ShieldCheck } from "lucide-react"

import { Thread } from "@/components/assistant-ui/elements/thread.aui"
import { Header, HeaderLink, Logo } from "@/components/brand"
import { UserMenu } from "@/components/sign-in"
import { TooltipProvider } from "@/components/ui/tooltip"
import { isPrivileged, useSession } from "@/lib/session"
import { config, controlLayer } from "@/lib/assistant"

function greeting() {
  const hour = new Date().getHours()
  if (hour < 12) return "Good morning"
  if (hour < 18) return "Good afternoon"
  return "Good evening"
}

function Welcome() {
  return <Greeting name={useSession()?.user.name} />
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

const bankChat = controlLayer()

export function Chat() {
  const runtime = useLocalRuntime(bankChat)
  const session = useSession()
  return (
    <AssistantRuntimeProvider runtime={runtime} config={config}>
      <TooltipProvider>
        <div className="flex h-svh flex-col">
          <Header product="Assistant">
            <span className="flex items-center gap-1.5 rounded-full border border-emerald-400/40 bg-emerald-400/10 px-2.5 py-1 text-xs text-emerald-300">
              <ShieldCheck className="size-3.5" />
              <span className="hidden sm:inline">
                Protected by AI control layer
              </span>
              <span className="sm:hidden">Protected</span>
            </span>
            {isPrivileged(session?.user) && (
              <HeaderLink href="/admin" label="Admin" icon={Shield} />
            )}
            <UserMenu />
          </Header>
          <div className="min-h-0 flex-1">
            <Thread components={{ Welcome }} />
          </div>
        </div>
      </TooltipProvider>
    </AssistantRuntimeProvider>
  )
}
