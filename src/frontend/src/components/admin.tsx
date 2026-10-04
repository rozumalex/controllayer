import {
  KeyRound,
  LayoutDashboard,
  Swords,
  Plug,
  ShieldAlert,
  SlidersHorizontal,
} from "lucide-react"
import { useEffect, useState } from "react"

import { Header, HeaderLink } from "@/components/brand"
import { Mcps } from "@/components/config"
import { Policy } from "@/components/controls"
import { Dashboard } from "@/components/dashboard"
import { Identity } from "@/components/identity"
import { UserMenu } from "@/components/sign-in"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { isPrivileged, useSession } from "@/lib/session"

// Each tab has its own path under /admin, so a tab can be linked and reloaded.
const TABS = [
  {
    path: "/admin",
    label: "Dashboard",
    icon: LayoutDashboard,
    Page: Dashboard,
  },
  { path: "/admin/mcps", label: "MCPs", icon: Plug, Page: Mcps },
  {
    path: "/admin/policy",
    label: "Policy",
    icon: SlidersHorizontal,
    Page: Policy,
  },
  {
    path: "/admin/idp",
    label: "Directory",
    icon: KeyRound,
    Page: Identity,
  },
]

function tabAt(path: string) {
  return TABS.find((tab) => tab.path === path.replace(/\/$/, "")) ?? TABS[0]
}

function useTab() {
  const [tab, setTab] = useState(() => tabAt(window.location.pathname))

  useEffect(() => {
    const onPop = () => setTab(tabAt(window.location.pathname))
    window.addEventListener("popstate", onPop)
    return () => window.removeEventListener("popstate", onPop)
  }, [])

  function open(path: string) {
    window.history.pushState(null, "", path)
    setTab(tabAt(path))
  }

  return [tab, open] as const
}

function Forbidden() {
  return (
    <div className="flex flex-col items-center gap-3 py-24 text-center">
      <ShieldAlert className="size-10 text-muted-foreground" />
      <h1 className="font-serif text-2xl font-semibold text-primary">
        Privileged users only
      </h1>
      <p className="max-w-sm text-sm text-muted-foreground">
        The admin pages need a privileged clearance. Sign in as a privileged
        user, or go back to the assistant.
      </p>
    </div>
  )
}

export function Admin() {
  const session = useSession()
  const [tab, open] = useTab()
  const allowed = isPrivileged(session?.user)

  return (
    <div className="flex min-h-svh flex-col bg-muted/40">
      <Header product="Admin">
        <HeaderLink href="/challenge" label="Challenge" icon={Swords} />
        <UserMenu />
      </Header>

      <main className="mx-auto flex w-full max-w-6xl flex-col gap-6 p-4 md:p-6">
        {allowed ? (
          <>
            <Tabs value={tab.path} onValueChange={open}>
              <TabsList variant="line">
                {TABS.map(({ path, label, icon: Icon }) => (
                  <TabsTrigger key={path} value={path}>
                    <Icon />
                    {label}
                  </TabsTrigger>
                ))}
              </TabsList>
            </Tabs>
            <tab.Page key={tab.path} />
          </>
        ) : (
          <Forbidden />
        )}
      </main>
    </div>
  )
}
