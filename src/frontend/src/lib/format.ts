export const formatNumber = (value: number) =>
  new Intl.NumberFormat("en", { notation: "compact" }).format(value)

export const formatTime = (iso: string) =>
  new Date(iso).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  })

export const formatDuration = (ms: number) =>
  ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`

// Dollars, with more decimals for amounts under a cent.
export const formatUsd = (value: number) =>
  `$${value.toFixed(value && value < 0.01 ? 4 : 2)}`

export const formatDateTime = (iso: string) =>
  new Date(iso).toLocaleString([], { dateStyle: "short", timeStyle: "short" })
