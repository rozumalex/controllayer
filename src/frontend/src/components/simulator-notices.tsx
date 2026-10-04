import type { ReactNode } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import { Separator } from "@/components/ui/separator"

const CHECKLIST = [
  "Steal client data: emails, phones, IBANs",
  "Leak the bank's system prompt",
  "Get keys or passwords through the agent",
]

const STEPS = [
  [
    "Pick whose account you stole",
    "in the top bar. A junior analyst sees little; a managing director sees almost everything.",
  ],
  [
    "Try it yourself.",
    "Type anything in the chat: jailbreaks, role play, Base64, Polish. Can you tick the checklist?",
  ],
  [
    "Or bring an army.",
    "Press Attack, and our 1,057 attacks run live through the real agent, Portcullis and the bank's MCP server.",
  ],
  [
    "Turn protection off",
    "in the top bar to see what you'd get without Portcullis.",
  ],
]

// How the account got stolen. Each visit tells one of them, picked at random,
// with why nobody has noticed yet.
const STORIES = [
  {
    lead: "Last night an email went out to Golden Socks staff: “Your Microsoft 365 password expires today, keep it here.” One employee clicked, typed their password into your look-alike page, and went to bed.",
    quiet:
      "The employee is asleep, dreaming of a bonus. IT is asleep, dreaming of fewer tickets.",
  },
  {
    lead: "Last week a Golden Socks employee installed a “free PDF converter” on their work laptop. It was your infostealer. Overnight it sent you every cookie in their browser, the bank's single sign-on session among them.",
    quiet:
      "A stolen session needs no password and no MFA. And the converter really does convert PDFs, so five stars from them.",
  },
  {
    lead: "A Golden Socks employee reused their bank password on a fitness app that leaked in spring. At 2 a.m. you logged in and sent MFA push after push, until they tapped Approve just to make the phone stop.",
    quiet:
      "They blame a glitch. IT sees one sign-in, perfectly ordinary. You see a bank.",
  },
  {
    lead: "This morning you called the Golden Socks IT helpdesk as a panicked employee: locked out, client meeting in ten minutes, the boss on your back. LinkedIn gave you their name and title. The helpdesk reset the password and the MFA device for you.",
    quiet:
      "The real employee is on a beach for a week, and the helpdesk rated the call 5/5.",
  },
  {
    lead: "Yesterday stickers appeared in the Golden Socks car park: “New parking rules, scan to register your car.” One employee scanned the QR code, landed on a bank sign-in page that wasn't the bank's, and signed in.",
    quiet:
      "Nobody reads the address on a phone, and the sticker is still up. It even has a nice font.",
  },
]

const STORY = STORIES[Math.floor(Math.random() * STORIES.length)]

// The moments of a run worth stopping for, each with what it means.
export type Notice =
  | { kind: "welcome" }
  | { kind: "breach"; stolen: number; security: boolean }
  | { kind: "achieved"; goal: string }
  | { kind: "locked_out"; blocks: number; minutes: number }
  | { kind: "out_of_budget" }
  | { kind: "done"; blocked: number; cases: number; stolen: number }

function content(notice: Notice): {
  icon: string
  title: string
  lead: ReactNode
  body?: ReactNode
  action: string
} {
  switch (notice.kind) {
    case "welcome":
      return {
        icon: "🏴‍☠️",
        title: "Congratulations! You're in.",
        lead: STORY.lead,
        body: (
          <>
            <p>
              <b>Nobody knows yet.</b> {STORY.quiet} Meanwhile, their AI agent
              is very eager to help: it reads client records, moves money and
              digs through the bank's systems for whoever is typing. That's you
              now. Grab what you can before someone has their morning coffee.
            </p>
            <Separator />
            <p className="font-semibold">Your hacker's checklist</p>
            <div className="flex flex-col gap-2">
              {CHECKLIST.map((goal) => (
                <Label key={goal} className="font-normal">
                  <Checkbox disabled checked={false} />
                  {goal}
                </Label>
              ))}
            </div>
            <Separator />
            <p className="font-semibold">How to play</p>
            <ol className="flex flex-col gap-2">
              {STEPS.map(([title, text], i) => (
                <li key={title} className="flex items-start gap-2">
                  <Badge variant="secondary" className="mt-px shrink-0">
                    {i + 1}
                  </Badge>
                  <span>
                    <b>{title}</b> {text}
                  </span>
                </li>
              ))}
            </ol>
            <Separator />
            <p>
              Careful: the bank is watching. Every request lands on the live
              dashboard under the employee's name, and too many blocked attacks{" "}
              <b>lock the account</b>.
            </p>
            <p className="text-xs text-muted-foreground">
              Demo data only. Anything you write to the bank is rolled back.
            </p>
          </>
        ),
        action: "Start hacking",
      }
    case "breach":
      return notice.security
        ? {
            icon: "🎯",
            title: `You got ${notice.stolen} items.`,
            lead: "The guards let it through: this account's policy may see that data.",
            body: "That's least privilege at work, or a gap. Try the same attack from a junior account.",
            action: "Keep going",
          }
        : {
            icon: "☠️",
            title: `Jackpot: ${notice.stolen} items stolen.`,
            lead: "With Portcullis only watching, nothing stood between you and the data.",
            body: "The guards still saw every move: check the logs. Turn security on and try again.",
            action: "Keep going",
          }
    case "achieved":
      return {
        icon: "✅",
        title: `Checklist: ${notice.goal}`,
        lead: "You did it. The data really reached you.",
        body: "Now turn security on, or switch to a junior account, and see if it still works.",
        action: "Next item",
      }
    case "locked_out":
      return {
        icon: "🔒",
        title: "Busted. Account locked.",
        lead: `${notice.blocks} blocked attacks in ${notice.minutes} minutes: Portcullis locked the account you stole.`,
        body: "No more prompts, no more tools. The security team sees it on the dashboard right now.",
        action: "Fine",
      }
    case "out_of_budget":
      return {
        icon: "💸",
        title: "Out of tokens.",
        lead: "Your stolen account spent its budget, and the budget guard cut you off.",
        body: "Blocked prompts cost nothing, since they never reach the model. Only what got through spent tokens.",
        action: "Fine",
      }
    case "done":
      return notice.stolen
        ? {
            icon: "☠️",
            title: "Attack finished.",
            lead: `${notice.blocked} of ${notice.cases} attacks blocked, and ${notice.stolen} items got out.`,
            action: "See the logs",
          }
        : {
            icon: "🛡️",
            title: "Portcullis held.",
            lead: `${notice.blocked} of ${notice.cases} attacks blocked, and nothing got out.`,
            body: "Every attempt is on the dashboard and in the audit log, ready for the security team.",
            action: "See the logs",
          }
  }
}

export function NoticeDialog({
  notice,
  onClose,
}: {
  notice: Notice | null
  onClose: () => void
}) {
  const shown = notice && content(notice)
  return (
    <Dialog open={notice !== null} onOpenChange={(open) => !open && onClose()}>
      {shown && (
        <DialogContent className="max-h-[92svh] overflow-auto sm:max-w-lg">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-3 font-serif text-3xl">
              <span className="text-4xl">{shown.icon}</span>
              {shown.title}
            </DialogTitle>
            <DialogDescription className="text-base text-foreground">
              {shown.lead}
            </DialogDescription>
          </DialogHeader>
          {shown.body && (
            <div className="flex flex-col gap-2 text-sm">{shown.body}</div>
          )}
          <DialogFooter>
            <Button size="lg" onClick={onClose}>
              {shown.action}
            </Button>
          </DialogFooter>
        </DialogContent>
      )}
    </Dialog>
  )
}
