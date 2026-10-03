import type { ComponentProps } from "react"

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
