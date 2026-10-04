import { Check, Copy, Plug } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useCopyToClipboard } from "@/hooks/use-copy-to-clipboard"
import { storedToken } from "@/lib/users"

// How to plug the user's own agent, such as Claude Code, into the gateway's
// MCP server. It signs in with the user's session token.
export function ConnectAgent() {
  const { isCopied, copyToClipboard } = useCopyToClipboard()
  const url = `${window.location.origin}/api/mcp`
  const command = `claude mcp add --transport http portcullis ${url} --header "Authorization: Bearer ${storedToken() ?? ""}"`
  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button variant="outline">
          <Plug /> Connect your agent
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Connect your agent</DialogTitle>
          <DialogDescription>
            Any MCP client gets the tools your role allows, and the blocked ones
            marked as blocked if your role shows them, through the same guards,
            and each call shows in the traces under your name.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-2">
          <Label>MCP URL</Label>
          <Input readOnly className="font-mono" value={url} />
        </div>
        <div className="grid gap-2">
          <Label>Claude Code</Label>
          <div className="flex gap-2">
            <Input readOnly className="font-mono" value={command} />
            <Button
              variant="outline"
              size="icon"
              title="Copy"
              onClick={() => copyToClipboard(command)}
            >
              {isCopied ? (
                <Check className="size-4" />
              ) : (
                <Copy className="size-4" />
              )}
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            The command holds your session token: keep it secret. It stops
            working when you sign out.
          </p>
        </div>
      </DialogContent>
    </Dialog>
  )
}
