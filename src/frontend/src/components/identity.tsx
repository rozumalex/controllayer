import {
  ArrowRight,
  CheckCircle2,
  Copy,
  RefreshCw,
  UserMinus,
  UserPlus,
  UserX,
  Users,
} from "lucide-react"
import { useEffect, useState, type ReactNode } from "react"

import { Employees } from "@/components/controls"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  fetchGroups,
  fetchLog,
  fetchScim,
  newScimToken,
  type DirectoryEvent,
  type DirectoryGroup,
  type ScimStatus,
} from "@/lib/identity"
import { fetchPolicy } from "@/lib/policy"

// The organization's directory as its IdP keeps it through SCIM: the
// connection, the groups and the roles they give, the provisioning log, then
// the people.
export function Identity() {
  return (
    <div className="flex flex-col gap-6">
      <ScimCard />
      <div className="grid gap-6 lg:grid-cols-2">
        <GroupsCard />
        <LogCard />
      </div>
      <Employees />
    </div>
  )
}

function ago(iso: string) {
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000)
  if (minutes < 1) return "just now"
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours} h ago`
  return `${Math.round(hours / 24)} d ago`
}

function CopyField({ value }: { value: string }) {
  return (
    <div className="flex gap-2">
      <Input readOnly className="font-mono" value={value} />
      <Button
        variant="outline"
        size="icon"
        title="Copy"
        onClick={() => navigator.clipboard.writeText(value)}
      >
        <Copy className="size-4" />
      </Button>
    </div>
  )
}

function Field({
  label,
  hint,
  children,
}: {
  label: string
  hint?: ReactNode
  children: ReactNode
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label>{label}</Label>
      {children}
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  )
}

// The IdP pushes users and groups here, and deactivates them, with the token.
function ScimCard() {
  const [status, setStatus] = useState<ScimStatus | null>(null)
  // The new token, shown until the page is left: only its hash is stored.
  const [token, setToken] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchScim()
      .then(setStatus)
      .catch((e: Error) => setError(e.message))
  }, [])

  async function makeToken() {
    if (
      status?.has_token &&
      !confirm("The IdP's current token stops working. Replace it?")
    )
      return
    setBusy(true)
    setError(null)
    try {
      const made = await newScimToken()
      setToken(made.token)
      setStatus((s) => s && { ...s, has_token: true })
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const connected = status?.has_token

  return (
    <Card>
      <CardHeader className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
          <CardTitle>Directory sync (SCIM)</CardTitle>
          <p className="text-sm text-muted-foreground">
            Your IdP, such as Okta or Entra ID, keeps people and groups in sync.
            Groups set roles, and roles set policies. People it deactivates lose
            access at once.
          </p>
        </div>
        {connected && (
          <Badge variant="secondary" className="gap-1.5">
            <CheckCircle2 className="size-3.5 text-emerald-600" />
            Connected
            {status.last_sync_at && ` · synced ${ago(status.last_sync_at)}`}
          </Badge>
        )}
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {!connected && (
          <ol className="list-decimal space-y-1 pl-5 text-sm text-muted-foreground">
            <li>Make a token below, and copy it with the base URL.</li>
            <li>
              In Okta, add the app &quot;SCIM 2.0 Test App (OAuth Bearer
              Token)&quot; and paste both on its Provisioning tab. In Entra ID,
              set an enterprise app&apos;s provisioning to Automatic.
            </li>
            <li>Turn on creating, updating and deactivating users.</li>
            <li>Push your groups, and assign them roles below.</li>
          </ol>
        )}
        {status && (
          <Field label="Base URL">
            <CopyField value={status.base_url} />
          </Field>
        )}
        {token && (
          <Field
            label="Token"
            hint="Copy it now: it isn't shown again. Send it as a bearer token."
          >
            <CopyField value={token} />
          </Field>
        )}
        <div className="flex flex-wrap items-center gap-3">
          <Button
            variant={connected ? "outline" : "default"}
            disabled={busy || !status}
            onClick={makeToken}
          >
            {connected ? "Replace token" : "Make a token"}
          </Button>
          {error && <p className="text-sm text-destructive">{error}</p>}
        </div>
      </CardContent>
    </Card>
  )
}

function GroupsCard() {
  const [groups, setGroups] = useState<DirectoryGroup[] | null>(null)
  // The roles with a policy of their own; the others follow the default.
  const [own, setOwn] = useState<Set<string>>(new Set())

  useEffect(() => {
    fetchGroups()
      .then(setGroups)
      .catch(() => setGroups([]))
    fetchPolicy()
      .then((overview) =>
        setOwn(
          new Set(overview.roles.filter((r) => r.customized).map((r) => r.role))
        )
      )
      .catch(() => setOwn(new Set()))
  }, [])

  return (
    <Card>
      <CardHeader>
        <CardTitle>Roles from groups</CardTitle>
        <p className="text-sm text-muted-foreground">
          Each IdP group gives a role, and the role&apos;s policy applies.
        </p>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Group</TableHead>
              <TableHead>Role · policy</TableHead>
              <TableHead className="text-right">People</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {groups?.length === 0 && (
              <TableRow>
                <TableCell
                  colSpan={3}
                  className="py-8 text-center text-muted-foreground"
                >
                  No groups synced yet.
                </TableCell>
              </TableRow>
            )}
            {groups?.map((group) => (
              <TableRow key={group.name}>
                <TableCell className="font-mono text-xs">
                  {group.name}
                </TableCell>
                <TableCell>
                  {group.role ? (
                    <a
                      className="inline-flex items-center gap-1.5 hover:underline"
                      href={`/admin/policy?role=${encodeURIComponent(group.role)}`}
                    >
                      {group.role}
                      {own.has(group.role) ? (
                        <Badge variant="secondary">own policy</Badge>
                      ) : (
                        <Badge variant="outline">default</Badge>
                      )}
                    </a>
                  ) : (
                    <span className="text-muted-foreground">No role</span>
                  )}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {group.members.toLocaleString()}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}

const ICONS: Record<DirectoryEvent["kind"], ReactNode> = {
  synced: <RefreshCw className="size-4 text-primary" />,
  created: <UserPlus className="size-4 text-emerald-600" />,
  joined: <Users className="size-4 text-emerald-600" />,
  left: <UserMinus className="size-4 text-muted-foreground" />,
  role: <ArrowRight className="size-4 text-primary" />,
  deactivated: <UserX className="size-4 text-destructive" />,
  reactivated: <UserPlus className="size-4 text-emerald-600" />,
}

function describe(event: DirectoryEvent): ReactNode {
  const name = <span className="font-medium">{event.name}</span>
  const group = <span className="font-mono text-xs">{event.data.group}</span>
  switch (event.kind) {
    case "synced":
      return (
        <>
          <span className="font-medium">Initial sync</span>:{" "}
          {event.data.users?.toLocaleString()} people, {event.data.groups}{" "}
          groups
        </>
      )
    case "created":
      return <>{name} was added</>
    case "joined":
      return (
        <>
          {name} joined {group}
        </>
      )
    case "left":
      return (
        <>
          {name} left {group}
        </>
      )
    case "role":
      return (
        <>
          {name}: {event.data.was ?? "no role"} →{" "}
          <span className="font-medium">
            {event.data.role ?? "default policy"}
          </span>
        </>
      )
    case "deactivated":
      return (
        <>
          {name} was deactivated
          {event.data.sessions
            ? ` · ${event.data.sessions} sessions ended`
            : ""}
        </>
      )
    case "reactivated":
      return <>{name} was reactivated</>
  }
}

function LogCard() {
  const [log, setLog] = useState<DirectoryEvent[] | null>(null)

  useEffect(() => {
    const load = () =>
      fetchLog()
        .then(setLog)
        .catch(() => setLog([]))
    void load()
    // The IdP pushes at any time.
    const timer = setInterval(load, 10_000)
    return () => clearInterval(timer)
  }, [])

  return (
    <Card>
      <CardHeader>
        <CardTitle>Provisioning log</CardTitle>
        <p className="text-sm text-muted-foreground">
          What the IdP changed, newest first.
        </p>
      </CardHeader>
      <CardContent>
        {log?.length === 0 && (
          <p className="py-8 text-center text-sm text-muted-foreground">
            Nothing synced yet.
          </p>
        )}
        <ol className="flex max-h-96 flex-col gap-3 overflow-y-auto">
          {log?.map((event) => (
            <li key={event.id} className="flex items-start gap-3 text-sm">
              <span className="mt-0.5">{ICONS[event.kind]}</span>
              <span className="flex-1">{describe(event)}</span>
              <time
                className="shrink-0 text-xs text-muted-foreground tabular-nums"
                dateTime={event.at}
                title={new Date(event.at).toLocaleString()}
              >
                {ago(event.at)}
              </time>
            </li>
          ))}
        </ol>
      </CardContent>
    </Card>
  )
}
