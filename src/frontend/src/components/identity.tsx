import { Copy, Plus, Trash2 } from "lucide-react"
import { useEffect, useState, type ReactNode } from "react"

import { Employees } from "@/components/controls"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { fetchPolicy, type RolePolicy } from "@/lib/policy"
import {
  deleteProvider,
  fetchProvider,
  fetchScim,
  newScimToken,
  saveProvider,
  type IdentityProvider,
  type RoleRule,
  type ScimStatus,
} from "@/lib/identity"

// The organization's identity provider, its SCIM provisioning, then the
// people who sign in.
export function Identity() {
  return (
    <div className="flex flex-col gap-6">
      <ProviderCard />
      <ScimCard />
      <Employees />
    </div>
  )
}

type Form = {
  name: string
  issuer: string
  client_id: string
  client_secret: string
  scopes: string
  domains: string
  role_rules: RoleRule[]
  default_role: string
  enabled: boolean
}

const EMPTY: Form = {
  name: "",
  issuer: "",
  client_id: "",
  client_secret: "",
  scopes: "openid profile email",
  domains: "",
  role_rules: [],
  default_role: "",
  enabled: true,
}

function formOf(provider: IdentityProvider): Form {
  return {
    ...provider,
    client_secret: "",
    domains: provider.domains.join(", "),
    default_role: provider.default_role ?? "",
  }
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

function ProviderCard() {
  const [saved, setSaved] = useState<IdentityProvider | null | undefined>()
  const [form, setForm] = useState<Form>(EMPTY)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<string | null>(null)
  // The organization's roles, to pick from and to show which policy a rule
  // lands on.
  const [roles, setRoles] = useState<RolePolicy[]>([])

  useEffect(() => {
    fetchPolicy()
      .then((overview) => setRoles(overview.roles))
      .catch(() => setRoles([]))
  }, [])

  const hasPolicy = (role: string) =>
    roles.some((r) => r.role === role && r.customized)
  const policyOf = (role: string) =>
    hasPolicy(role) ? `${role} policy` : "default policy"

  useEffect(() => {
    fetchProvider()
      .then((provider) => {
        setSaved(provider)
        if (provider) setForm(formOf(provider))
      })
      .catch((e: Error) => setError(e.message))
  }, [])

  const set = (changes: Partial<Form>) => {
    setDone(null)
    setForm((form) => ({ ...form, ...changes }))
  }
  const setRule = (index: number, changes: Partial<RoleRule>) =>
    set({
      role_rules: form.role_rules.map((rule, i) =>
        i === index ? { ...rule, ...changes } : rule
      ),
    })

  async function act(
    action: () => Promise<IdentityProvider | null>,
    note: string
  ) {
    setBusy(true)
    setError(null)
    try {
      const provider = await action()
      setSaved(provider)
      setForm(provider ? formOf(provider) : EMPTY)
      setDone(note)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const save = () =>
    act(
      () =>
        saveProvider({
          ...form,
          domains: form.domains.split(/[\s,]+/).filter(Boolean),
          default_role: form.default_role || null,
          // Blank keeps the saved secret.
          client_secret: form.client_secret || undefined,
        }),
      "Saved. Sign-ins use it from now on."
    )

  if (saved === undefined && !error) return null

  return (
    <Card>
      <CardHeader className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-col gap-1">
          <CardTitle>Identity provider</CardTitle>
          <p className="text-sm text-muted-foreground">
            Your IAM over OpenID Connect. Claims set roles and policies.
          </p>
        </div>
        {saved && (
          <div className="flex items-center gap-2 text-sm">
            <Switch
              checked={form.enabled}
              onCheckedChange={(enabled) => set({ enabled })}
            />
            {form.enabled ? "On" : "Off"}
          </div>
        )}
      </CardHeader>
      <CardContent className="flex flex-col gap-6">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Name">
            <Input
              placeholder="Acme Okta"
              value={form.name}
              onChange={(e) => set({ name: e.target.value })}
            />
          </Field>
          <Field label="Issuer URL" hint="Okta, Entra ID, Google, Keycloak…">
            <Input
              placeholder="https://acme.okta.com"
              value={form.issuer}
              onChange={(e) => set({ issuer: e.target.value })}
            />
          </Field>
          <Field label="Client ID">
            <Input
              value={form.client_id}
              onChange={(e) => set({ client_id: e.target.value })}
            />
          </Field>
          <Field
            label="Client secret"
            hint={
              saved?.has_secret
                ? "Saved. Blank keeps it."
                : "Optional with PKCE."
            }
          >
            <Input
              type="password"
              autoComplete="off"
              value={form.client_secret}
              onChange={(e) => set({ client_secret: e.target.value })}
            />
          </Field>
          <Field label="Email domains" hint="These emails sign in here.">
            <Input
              placeholder="acme.com, acme.io"
              value={form.domains}
              onChange={(e) => set({ domains: e.target.value })}
            />
          </Field>
          <Field label="Scopes">
            <Input
              value={form.scopes}
              onChange={(e) => set({ scopes: e.target.value })}
            />
          </Field>
        </div>

        {saved && (
          <Field
            label="Redirect URI"
            hint="Register it with your provider as the sign-in redirect."
          >
            <CopyField value={saved.redirect_uri} />
          </Field>
        )}

        <div className="flex flex-col gap-3">
          <div>
            <Label>Roles from claims</Label>
            <p className="text-xs text-muted-foreground">First match wins.</p>
          </div>
          {form.role_rules.map((rule, index) => (
            <div
              key={index}
              className="grid gap-2 sm:grid-cols-[1fr_1fr_1fr_auto_auto]"
            >
              <Input
                placeholder="Claim, such as groups"
                value={rule.claim}
                onChange={(e) => setRule(index, { claim: e.target.value })}
              />
              <Input
                placeholder="Value"
                value={rule.value}
                onChange={(e) => setRule(index, { value: e.target.value })}
              />
              <Input
                placeholder="Role"
                list="roles"
                value={rule.role}
                onChange={(e) => setRule(index, { role: e.target.value })}
              />
              <label className="flex items-center gap-2 text-sm">
                <Checkbox
                  checked={rule.admin}
                  onCheckedChange={(admin) =>
                    setRule(index, { admin: admin === true })
                  }
                />
                Admin
              </label>
              {rule.role && (
                <p className="text-xs text-muted-foreground sm:order-last sm:col-span-5">
                  {rule.value || "…"} in {rule.claim || "…"} → {rule.role} ·{" "}
                  {policyOf(rule.role)}
                  {rule.admin && " · admin"}
                  {saved && !hasPolicy(rule.role) && (
                    <>
                      {" · "}
                      <a
                        className="text-primary underline-offset-4 hover:underline"
                        href={`/admin/policy?role=${encodeURIComponent(rule.role)}`}
                      >
                        Set a policy →
                      </a>
                    </>
                  )}
                </p>
              )}
              <Button
                variant="ghost"
                size="icon"
                title="Remove the rule"
                onClick={() =>
                  set({
                    role_rules: form.role_rules.filter((_, i) => i !== index),
                  })
                }
              >
                <Trash2 className="size-4" />
              </Button>
            </div>
          ))}
          <datalist id="roles">
            {roles.map((r) => (
              <option key={r.role} value={r.role} />
            ))}
          </datalist>
          <div>
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                set({
                  role_rules: [
                    ...form.role_rules,
                    { claim: "groups", value: "", role: "", admin: false },
                  ],
                })
              }
            >
              <Plus className="size-4" /> Add a rule
            </Button>
          </div>
          <Field
            label="Default role"
            hint={
              form.default_role
                ? `No match: ${policyOf(form.default_role)}.`
                : "No match: blank refuses sign-in."
            }
          >
            <Input
              className="sm:max-w-xs"
              list="roles"
              value={form.default_role}
              onChange={(e) => set({ default_role: e.target.value })}
            />
          </Field>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <Button disabled={busy} onClick={save}>
            {saved ? "Save" : "Connect"}
          </Button>
          {saved && (
            <Button
              variant="ghost"
              disabled={busy}
              onClick={() =>
                act(async () => (await deleteProvider(), null), "Disconnected.")
              }
            >
              Disconnect
            </Button>
          )}
          {error && <p className="text-sm text-destructive">{error}</p>}
          {done && !error && (
            <p className="text-sm text-muted-foreground">{done}</p>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

// The IdP pushes users and groups here, and deactivates them, with this token.
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
      setStatus({ base_url: made.base_url, has_token: true })
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card>
      <CardHeader className="flex flex-col gap-1">
        <CardTitle>Provisioning (SCIM)</CardTitle>
        <p className="text-sm text-muted-foreground">
          Your IdP syncs people and groups. Groups set roles through the rules
          above, and people it deactivates lose access at once.
        </p>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
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
            variant={status?.has_token ? "outline" : "default"}
            disabled={busy || !status}
            onClick={makeToken}
          >
            {status?.has_token ? "Replace token" : "Make a token"}
          </Button>
          {status?.has_token && !token && (
            <p className="text-sm text-muted-foreground">A token is set.</p>
          )}
          {error && <p className="text-sm text-destructive">{error}</p>}
        </div>
      </CardContent>
    </Card>
  )
}
