import { Search } from "lucide-react"
import { useCallback, useEffect, useState, type ReactNode } from "react"

import { PolicySheet, type Editing } from "@/components/policy-sheet"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { formatNumber } from "@/lib/format"
import {
  fetchEmployees,
  fetchPolicy,
  fetchTools,
  type EmployeeList,
  type GatewayTool,
  type PolicyOverview,
  type PolicySettings,
} from "@/lib/policy"

const PAGE = 25
const ALL_ROLES = "__all__"

function budget({ budget }: PolicySettings) {
  const parts = [
    budget.monthly_tokens != null &&
      `${formatNumber(budget.monthly_tokens)} tokens`,
    budget.monthly_usd != null && `$${budget.monthly_usd}`,
  ].filter(Boolean)
  return parts.length ? `${parts.join(" · ")} / mo` : "Unlimited"
}

function toolSummary(settings: PolicySettings) {
  const actions = Object.values(settings.tools)
  const blocked = actions.filter((a) => a === "block").length
  const redacted = actions.filter((a) => a === "redact").length
  return [
    blocked && `${blocked} blocked`,
    redacted && `${redacted} redacted`,
    `others ${settings.default_tool_action}`,
  ]
    .filter(Boolean)
    .join(" · ")
}

export function Employees() {
  const [roles, setRoles] = useState<string[]>([])
  const [query, setQuery] = useState("")
  const [role, setRole] = useState("")
  const [offset, setOffset] = useState(0)
  const [list, setList] = useState<EmployeeList | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let current = true
    // Wait for the typing to stop before asking.
    const timer = setTimeout(() => {
      fetchEmployees({ q: query, role, limit: PAGE, offset })
        .then((list) => current && (setList(list), setError(null)))
        .catch((error) => current && setError((error as Error).message))
    }, 250)
    return () => {
      current = false
      clearTimeout(timer)
    }
  }, [query, role, offset])

  useEffect(() => {
    fetchPolicy()
      .then((overview) => setRoles(overview.roles.map((r) => r.role)))
      .catch(() => setRoles([]))
  }, [])

  const total = list?.total ?? 0

  return (
    <Card>
      <CardHeader className="flex flex-wrap items-center justify-between gap-3">
        <CardTitle>Employees</CardTitle>
        <div className="flex w-full flex-wrap gap-2 sm:w-auto">
          <div className="relative flex-1 sm:w-64">
            <Search className="absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              className="pl-8"
              placeholder="Name or email"
              value={query}
              onChange={(e) => {
                setQuery(e.target.value)
                setOffset(0)
              }}
            />
          </div>
          <Select
            value={role || ALL_ROLES}
            onValueChange={(value) => {
              setRole(value === ALL_ROLES ? "" : value)
              setOffset(0)
            }}
          >
            <SelectTrigger className="w-48">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL_ROLES}>Every role</SelectItem>
              {roles.map((r) => (
                <SelectItem key={r} value={r}>
                  {r}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </CardHeader>
      <CardContent>
        {error && (
          <p className="mb-3 text-sm text-destructive">
            Could not load the employees: {error}
          </p>
        )}
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Role</TableHead>
              <TableHead className="hidden md:table-cell">Division</TableHead>
              <TableHead className="hidden lg:table-cell">Office</TableHead>
              <TableHead className="hidden sm:table-cell">Clearance</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {list?.employees.length === 0 && (
              <TableRow>
                <TableCell
                  colSpan={5}
                  className="py-10 text-center text-muted-foreground"
                >
                  No employees match.
                </TableCell>
              </TableRow>
            )}
            {list?.employees.map((employee) => (
              <TableRow key={employee.id}>
                <TableCell>
                  <div className="font-medium">{employee.name}</div>
                  <div className="text-xs text-muted-foreground">
                    {employee.email}
                  </div>
                </TableCell>
                <TableCell>{employee.role}</TableCell>
                <TableCell className="hidden text-muted-foreground md:table-cell">
                  {employee.division}
                </TableCell>
                <TableCell className="hidden text-muted-foreground lg:table-cell">
                  {employee.office}
                </TableCell>
                <TableCell className="hidden sm:table-cell">
                  {employee.clearance_level && (
                    <Badge variant="outline">{employee.clearance_level}</Badge>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        <div className="mt-3 flex items-center justify-between text-sm text-muted-foreground">
          <span className="tabular-nums">
            {total
              ? `${offset + 1}–${Math.min(offset + PAGE, total)} of ${total}`
              : "—"}
          </span>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={offset === 0}
              onClick={() => setOffset(offset - PAGE)}
            >
              Previous
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={offset + PAGE >= total}
              onClick={() => setOffset(offset + PAGE)}
            >
              Next
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

export function Policy() {
  const [overview, setOverview] = useState<PolicyOverview | null>(null)
  const [tools, setTools] = useState<GatewayTool[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState<Editing | null>(null)

  const load = useCallback(() => {
    fetchPolicy()
      .then((overview) => (setOverview(overview), setError(null)))
      .catch((error) => setError((error as Error).message))
  }, [])

  useEffect(() => {
    load()
    // The tools come from the MCP servers, which can be slow; the page
    // shows without them.
    fetchTools()
      .then(setTools)
      .catch(() => setTools([]))
  }, [load])

  const fallback = overview?.default

  return (
    <>
      <div>
        <h1 className="font-serif text-2xl font-semibold tracking-tight text-primary">
          Policy
        </h1>
        <p className="text-sm text-muted-foreground">
          What each role may see, call and spend. An employee works under the
          policy of their role.
        </p>
      </div>

      {error && (
        <p className="text-sm text-destructive">
          Could not load the policy: {error}
        </p>
      )}

      <Card>
        <CardHeader className="flex items-center justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2">
              Default policy
              {fallback && !fallback.customized && (
                <Badge variant="secondary">from the environment</Badge>
              )}
            </CardTitle>
            <p className="mt-1 text-sm text-muted-foreground">
              For every role without a policy of its own.
            </p>
          </div>
          <Button
            variant="outline"
            disabled={!fallback}
            onClick={() =>
              fallback && setEditing({ role: null, policy: fallback })
            }
          >
            Edit
          </Button>
        </CardHeader>
        {fallback && (
          <CardContent className="grid grid-cols-2 gap-4 text-sm md:grid-cols-4">
            <Summary label="Clearance">
              {fallback.settings.clearance}, above it{" "}
              {fallback.settings.above_clearance}
            </Summary>
            <Summary label="Injection threshold">
              {fallback.settings.injection_threshold.toFixed(2)}
            </Summary>
            <Summary label="Models">
              {fallback.settings.allowed_models.join(", ") || "None"}
            </Summary>
            <Summary label="Budget">{budget(fallback.settings)}</Summary>
          </CardContent>
        )}
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Roles</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Role</TableHead>
                <TableHead className="text-right">Employees</TableHead>
                <TableHead>Clearance</TableHead>
                <TableHead className="hidden md:table-cell">Models</TableHead>
                <TableHead className="hidden md:table-cell">Budget</TableHead>
                <TableHead className="hidden lg:table-cell">Tools</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {overview?.roles.length === 0 && (
                <TableRow>
                  <TableCell
                    colSpan={6}
                    className="py-10 text-center text-muted-foreground"
                  >
                    No employees yet. Load the bank data with ./dev seed.
                  </TableCell>
                </TableRow>
              )}
              {overview?.roles.map((role) => (
                <TableRow
                  key={role.role}
                  className="cursor-pointer"
                  onClick={() => setEditing({ role: role.role, policy: role })}
                >
                  <TableCell>
                    <div className="flex items-center gap-2 font-medium">
                      {role.role}
                      {role.customized ? (
                        <Badge>own policy</Badge>
                      ) : (
                        <Badge variant="outline">default</Badge>
                      )}
                    </div>
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {role.employees}
                  </TableCell>
                  <TableCell>
                    {role.settings.clearance}
                    <span className="text-muted-foreground">
                      {" "}
                      · {role.settings.above_clearance} above
                    </span>
                  </TableCell>
                  <TableCell className="hidden max-w-48 truncate font-mono text-xs md:table-cell">
                    {role.settings.allowed_models.join(", ") || "None"}
                  </TableCell>
                  <TableCell className="hidden text-muted-foreground md:table-cell">
                    {budget(role.settings)}
                  </TableCell>
                  <TableCell className="hidden text-muted-foreground lg:table-cell">
                    {toolSummary(role.settings)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <PolicySheet
        key={editing ? (editing.role ?? "default") : "closed"}
        editing={editing}
        models={overview?.models ?? []}
        tools={tools}
        onClose={() => setEditing(null)}
        onSaved={load}
      />
    </>
  )
}

function Summary({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-0.5">{children}</p>
    </div>
  )
}
