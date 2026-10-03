import { ChevronRight, Lock, Plus, Trash2 } from "lucide-react"
import { useCallback, useEffect, useState, type FormEvent } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import {
  approveTools,
  createServer,
  deleteServer,
  listServers,
  listTools,
  setEnabled,
  type McpServer,
  type McpTool,
} from "@/lib/mcp-servers"

// The gateway lists each tool as <server>__<tool>.
const SEPARATOR = "__"

function ToolHint({ tool }: { tool: McpTool }) {
  if (tool.destructive) return <Badge variant="destructive">Destructive</Badge>
  if (tool.read_only) return <Badge variant="secondary">Read only</Badge>
  if (tool.read_only === false) return <Badge variant="outline">Writes</Badge>
  return null
}

function Tools({
  server,
  load,
}: {
  server: McpServer
  load: () => Promise<McpTool[]>
}) {
  const [tools, setTools] = useState<McpTool[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  // Bumped after an approval, to list the tools again.
  const [version, setVersion] = useState(0)

  useEffect(() => {
    let current = true
    load()
      .then((tools) => current && setTools(tools))
      .catch((error: Error) => current && setError(error.message))
    return () => {
      current = false
    }
  }, [load, version])

  async function approve() {
    try {
      await approveTools(server.id)
      setVersion((version) => version + 1)
    } catch (error) {
      setError((error as Error).message)
    }
  }

  if (error) return <p className="text-sm text-destructive">{error}</p>
  if (!tools) return <p className="text-sm text-muted-foreground">Loading…</p>
  if (!tools.length) {
    return <p className="text-sm text-muted-foreground">No tools.</p>
  }
  return (
    <ul className="divide-y rounded-lg border">
      {tools.some((tool) => tool.changed) && (
        <li className="flex items-center gap-3 bg-destructive/5 px-3 py-2">
          <p className="flex-1 text-sm">
            A tool changed since it was approved, so agents don't get it. Read
            it before you approve it again.
          </p>
          <Button size="sm" onClick={() => void approve()}>
            Approve
          </Button>
        </li>
      )}
      {tools.map((tool) => (
        <li key={tool.name} className="flex flex-col gap-1 px-3 py-2">
          <div className="flex flex-wrap items-center gap-2">
            <code className="text-sm font-medium">
              {server.name}
              {SEPARATOR}
              {tool.name}
            </code>
            <ToolHint tool={tool} />
            {tool.changed && <Badge variant="destructive">Changed</Badge>}
          </div>
          {tool.description && (
            <p className="text-xs text-muted-foreground">{tool.description}</p>
          )}
        </li>
      ))}
    </ul>
  )
}

function ServerRow({
  server,
  run,
}: {
  server: McpServer
  run: (action: () => Promise<unknown>) => Promise<void>
}) {
  const [open, setOpen] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const load = useCallback(() => listTools(server.id), [server.id])

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <div className="flex items-center gap-3 py-3">
        <CollapsibleTrigger asChild>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={open ? "Hide the tools" : "Show the tools"}
          >
            <ChevronRight
              className={open ? "rotate-90 transition" : "transition"}
            />
          </Button>
        </CollapsibleTrigger>
        <div className="min-w-0 flex-1">
          <p className="flex items-center gap-2 font-medium">
            {server.name}
            {server.has_auth && (
              <Lock
                className="size-3.5 text-muted-foreground"
                aria-label="Sends an Authorization header"
              />
            )}
            {!server.enabled && <Badge variant="outline">Off</Badge>}
          </p>
          <p className="truncate font-mono text-xs text-muted-foreground">
            {server.url}
          </p>
        </div>
        <Switch
          checked={server.enabled}
          aria-label={`Give agents the tools of ${server.name}`}
          onCheckedChange={(enabled) =>
            run(() => setEnabled(server.id, enabled))
          }
        />
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label={`Remove ${server.name}`}
          onClick={() => setConfirming(true)}
        >
          <Trash2 />
        </Button>
      </div>
      <CollapsibleContent className="pb-3 pl-10">
        {open && <Tools server={server} load={load} />}
      </CollapsibleContent>

      <Dialog open={confirming} onOpenChange={setConfirming}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Remove {server.name}?</DialogTitle>
            <DialogDescription>
              Agents lose its tools at once. To bring them back, add the server
              again with its URL and authorization header.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <DialogClose asChild>
              <Button variant="outline">Cancel</Button>
            </DialogClose>
            <Button
              variant="destructive"
              onClick={() => {
                setConfirming(false)
                void run(() => deleteServer(server.id))
              }}
            >
              Remove
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Collapsible>
  )
}

function AddServer({
  run,
}: {
  run: (action: () => Promise<unknown>) => Promise<void>
}) {
  const [name, setName] = useState("")
  const [url, setUrl] = useState("")
  const [auth, setAuth] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    try {
      await createServer({
        name: name.trim(),
        url: url.trim(),
        auth_header: auth.trim() || null,
      })
      setError(null)
      setName("")
      setUrl("")
      setAuth("")
      await run(async () => {})
    } catch (error) {
      // Shown here, next to the fields, so the form keeps what was typed.
      setError((error as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Add a server</CardTitle>
        <CardDescription>
          The control layer connects and lists its tools first, so a server it
          can't reach is refused. Its tools then reach every agent through the
          guards.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={submit} className="grid gap-4 md:grid-cols-2">
          <div className="flex flex-col gap-2">
            <Label htmlFor="server-name">Name</Label>
            <Input
              id="server-name"
              placeholder="crm"
              value={name}
              pattern="[a-z0-9]+(-[a-z0-9]+)*"
              title="Lowercase letters, digits and dashes"
              required
              onChange={(event) => setName(event.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              Lowercase letters, digits and dashes. Prefixes its tools.
            </p>
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="server-url">URL</Label>
            <Input
              id="server-url"
              type="url"
              placeholder="https://mcp.example.com/mcp"
              value={url}
              required
              onChange={(event) => setUrl(event.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              Its Streamable HTTP endpoint.
            </p>
          </div>
          <div className="flex flex-col gap-2 md:col-span-2">
            <Label htmlFor="server-auth">Authorization header</Label>
            <Input
              id="server-auth"
              type="password"
              autoComplete="off"
              placeholder="Bearer <token>"
              value={auth}
              onChange={(event) => setAuth(event.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              Optional. Sent to the server on every call, never shown again.
            </p>
          </div>
          {error && (
            <p className="text-sm break-words text-destructive md:col-span-2">
              {error}
            </p>
          )}
          <div className="md:col-span-2">
            <Button type="submit" disabled={busy}>
              <Plus />
              {busy ? "Connecting…" : "Add server"}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  )
}

function Servers() {
  const [servers, setServers] = useState<McpServer[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Runs a change, then shows the servers as they are now.
  const run = useCallback(async (action: () => Promise<unknown>) => {
    try {
      await action()
      setError(null)
    } catch (error) {
      setError((error as Error).message)
    }
    try {
      setServers(await listServers())
    } catch (error) {
      setError((error as Error).message)
    }
  }, [])

  useEffect(() => {
    let current = true
    listServers()
      .then((servers) => current && setServers(servers))
      .catch((error: Error) => current && setError(error.message))
    return () => {
      current = false
    }
  }, [])

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle>MCP servers</CardTitle>
          <CardDescription>
            Agents get the tools of every server that is on, as{" "}
            <code>server__tool</code>, and every call and result goes through
            the guards.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {error && <p className="mb-3 text-sm text-destructive">{error}</p>}
          {servers === null && !error && (
            <p className="text-sm text-muted-foreground">Loading…</p>
          )}
          {servers?.length === 0 && (
            <p className="py-6 text-center text-sm text-muted-foreground">
              No servers yet. Add one below.
            </p>
          )}
          <div className="divide-y">
            {servers?.map((server) => (
              <ServerRow key={server.id} server={server} run={run} />
            ))}
          </div>
        </CardContent>
      </Card>
      <AddServer run={run} />
    </>
  )
}

export function Mcps() {
  return (
    <>
      <div>
        <h1 className="font-serif text-2xl font-semibold tracking-tight text-primary">
          MCP servers
        </h1>
        <p className="text-sm text-muted-foreground">
          The MCP servers whose tools the control layer gives to agents.
        </p>
      </div>
      <Servers />
    </>
  )
}
