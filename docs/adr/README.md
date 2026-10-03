# Architecture decision records

An architecture decision record (ADR) is a short note about one decision that shapes the project: what we chose, why, and what we gave up. Code shows what the project does. ADRs keep the reasons, so nobody has to guess them from the git history, and nobody undoes a decision without knowing why it was made.

## When to write one

Write an ADR when a decision is hard to undo or affects more than the code you are changing, for example:

- a new service, library or external tool, such as a database, a queue or a monitoring service;
- a pattern the rest of the code must follow;
- a choice between options that a reviewer would ask about.

Do not write one for a change that the code or the commit message explains well enough.

## How to write one

1. Copy `template.md` to `NNNN-short-title.md`, with the next free number, for example `0003-use-redis-for-the-cache.md`.
2. Fill in every section. Keep it short: one page is enough.
3. Add it to the list below, and commit it in the same pull request as the change it describes.

Do not rewrite an accepted ADR when the decision changes. Write a new ADR, and set the old one's status to `Superseded by [NNNN](NNNN-title.md)`. Fixing typos and broken links is fine.

## Records

| Number                                                   | Title                                                       | Status   |
| -------------------------------------------------------- | ----------------------------------------------------------- | -------- |
| [0001](0001-build-the-hackathon-template-as-one-repo.md) | Build the hackathon template as one repo with a fixed stack | Accepted |
| [0002](0002-start-new-relic-with-newrelic-admin.md)      | Start New Relic with newrelic-admin                         | Accepted |

Start with [0001](0001-build-the-hackathon-template-as-one-repo.md): it describes the whole repo and why it is built this way.
