import type { LucideIcon } from "lucide-react"
import type { ComponentProps, ReactNode } from "react"

// Golden Socks, the fictional bank whose employees use the assistant.
export const COMPANY = "Golden Socks"

export function Logo(props: ComponentProps<"svg">) {
  return (
    <svg viewBox="0 0 32 32" aria-hidden="true" {...props}>
      <path
        d="M9 3h10v13l6.5 4.2a3.6 3.6 0 0 1-3.9 6.1l-8.1 1.3A5 5 0 0 1 9 22.6Z"
        fill="var(--gold)"
      />
      <path d="M9 7.5h10" stroke="var(--primary)" strokeWidth="1.6" />
      <path d="M9 10.5h10" stroke="var(--primary)" strokeWidth="1.6" />
    </svg>
  )
}

// The navy bar on top of every page: the brand, the page's name, and the
// page's own items on the right.
export function Header({
  product,
  children,
}: {
  product: string
  children?: ReactNode
}) {
  return (
    <header className="flex h-14 shrink-0 items-center gap-3 border-b border-gold/30 bg-primary px-4 text-primary-foreground md:px-6">
      <a href="/" className="flex items-center gap-3">
        <Logo className="size-7" />
        <span className="font-serif text-lg font-semibold tracking-tight whitespace-nowrap">
          {COMPANY}
        </span>
      </a>
      <span className="h-5 w-px bg-primary-foreground/25" />
      <span className="text-sm whitespace-nowrap text-primary-foreground/80">
        {product}
      </span>
      <div className="ml-auto flex items-center gap-3">{children}</div>
    </header>
  )
}

// A link to another page, for the right of the header.
export function HeaderLink({
  href,
  label,
  icon: Icon,
}: {
  href: string
  label: string
  icon: LucideIcon
}) {
  return (
    <a
      href={href}
      aria-label={label}
      className="flex items-center gap-1.5 rounded-md px-2 py-1 text-sm text-primary-foreground/80 hover:bg-primary-foreground/10 hover:text-primary-foreground"
    >
      <Icon className="size-4" />
      <span className="hidden sm:inline">{label}</span>
    </a>
  )
}
