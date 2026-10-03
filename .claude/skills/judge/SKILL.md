---
name: judge
description: Check the work against the hackathon's own documents in local/rules, such as the task, the rules, the deadlines and the judging criteria. It reports how much time is left, how well the branch fits the task, a mock jury score and what the submission still lacks. Use it when the user types /judge, before shipping a feature, when the team picks or changes a task, or when a deadline is close.
---

# Judge

The jury reads each submission for only a few minutes. Teams lose points when they drift off the task, miss a deadline, or leave the jury unable to run or understand the project. Check all of that against the organizers' documents, and tell the team what earns the most points next.

Every fact comes from `local/rules`, never from memory or from this file. The organizers change tasks, times and criteria, and the team adds documents during the event. So check the folder on every run, and read again only what changed since the last run.

## 1. Read local/rules

```sh
ls -la local/rules
date "+%A %Y-%m-%d %H:%M %Z"
```

If the folder is missing or empty, stop. Tell the user to put the hackathon documents in `local/rules`: the rules, the participant guide, and the description of the task they picked, as PDF, Markdown, text or screenshots. `local/` is gitignored, so the documents stay out of the repo.

### The cache

Reading every document in full takes a lot of context, so the skill keeps what it learned in `local/.judge-cache/`. That folder is outside `local/rules`, so it never counts as a document.

- `manifest.txt`: the checksum of every file in `local/rules`, from the last time the digest was built.
- `digest.md`: the facts listed under [What to write down](#what-to-write-down), each with its document and page, and the time it was built at the top.
- `text/<file>.txt`: the extracted text of each PDF, so you can check one page again without reading the whole document.

Compare the folder with the manifest:

```sh
mkdir -p local/.judge-cache/text
(cd local/rules && find . -type f ! -name '.*' -print0 | sort -z | xargs -0 shasum) > local/.judge-cache/manifest.new
diff local/.judge-cache/manifest.txt local/.judge-cache/manifest.new
```

- **No difference:** read only `digest.md`, and go on to step 2. When you need a quote or a detail the digest left out, grep `text/` for it, and don't read the whole PDF.
- **Files added, changed or removed:** read only those files, as described below, and update the digest. Keep the facts from the files that didn't change.
- **No manifest yet, the user typed `/judge --fresh`, or the digest looks wrong:** read every file and build the digest from scratch.

Afterwards, `mv local/.judge-cache/manifest.new local/.judge-cache/manifest.txt`. If a change moved a deadline, changed a weight or added a requirement, say so at the top of the report, for example "Changed since the last run: the task now requires X".

### Reading a file

- Markdown and text: read them in full.
- PDF: extract the text with `pdftotext -layout <file> local/.judge-cache/text/<file>.txt` and read all of it. If `pdftotext` is missing or gives no text, read the PDF with the Read tool, in batches of pages.
- Images: look at them with the Read tool. For images that only show maps or floor plans, write one line in the digest, and don't read them again unless the user asks about the venue.
- Files that are not in English: read them in the original, but write the digest in English. If a document has an English version inside it, use that one.

### What to write down

- **Deadlines:** every date and time with what it requires, such as a checkpoint, the final submission or a code freeze.
- **Judging criteria:** each criterion with its weight, the score scale, the stages, and any minimum score.
- **Submission requirements:** the platform, the fields and materials, and rules about where the code comes from, such as code written during the event, or AI tools and libraries that must be disclosed.
- **The task:** the problem, the required features, the expected deliverables, and any criteria that apply only to this task, sorted with MoSCoW as described in step 3.
- **Rubric anchors:** for each criterion, what the low, middle and top of the scale look like for this task, as described in step 3. Write them once, so scores stay consistent between runs.

A partner task can replace the general criteria with its own. When two documents disagree, the more specific one wins: the task over the guide, and the guide over the general rules. Write the conflict in the digest, and name it in the report.

If no document describes the task the team picked, still run the clock and the submission checks. Mark the task fit as unknown, and ask the user to add the task description to `local/rules`.

## 2. Read the work

```sh
git fetch --quiet origin
git log --oneline origin/main
git diff --stat "$(git merge-base HEAD origin/main)"
git status --short
```

Also read the README and anything the submission will show the jury, such as a demo link, screenshots or a pitch. Judge the whole project: what is on `main`, plus this branch. When a criterion depends on the running app, such as design or usability, look at the code for it. Don't start the app unless the user asks.

## 3. Apply the frameworks

Use these standard methods, so each run judges the work the same way. The methods are fixed, but every input comes from the documents in step 1. Take the MoSCoW list and the rubric anchors from the digest, and build them only when the digest has none yet or the task changed.

- **Problem statement (Jobs to Be Done).** Write the project in one line: "When <situation>, <user> wants to <job>, so they can <outcome>." Take it from the README and the submission. If you can't write it, or it doesn't match the task, Idea and Relation to the category lose points. Say so first, because every other fix depends on it.
- **MoSCoW for the task.** Sort the task's requirements into **Must** (the task says it is required, or the jury can't judge without it), **Should** (named in the task or its criteria), **Could** (nice extras) and **Won't** (out of scope for the time left). Check each against the work. A missing Must matters more than any Could.
- **Anchored rubric for the score.** Before you score, write what the low, middle and top of the scale look like for each criterion, in terms of this task. For example, on a 0–10 scale for Design: 2 = screens with no flow, 5 = a working flow with rough UI, 8 = a clear flow with a consistent UI, 10 = polished and tested with users. Then put the work on the anchors, and name the evidence. This keeps scores consistent between runs.
- **Cold read.** Act as a juror with a few minutes and only what the submission shows: the README, the description, the demo and the screenshots, not the code or this conversation. Can you tell what was built, how it works and how it fits the task? Each "no" is a gap in the submission.
- **Pre-mortem.** Assume the project failed to reach the final. Write the three likeliest reasons, such as a missed deadline, a demo that doesn't run, a weak link to the task, or AI tools or libraries left undisclosed.
- **Timebox.** Count back from the next deadline. Keep the last part of the time for the submission alone: write-up, demo, checks and upload. Use about a fifth of the time left, at least 1 hour before a final deadline. Name the time when feature work must stop.
- **ICE for the next steps.** Score each possible action 1–10 on **Impact** (the weighted rubric points it would add), **Confidence** (how sure you are that it adds them) and **Ease** (how fast it is, against the time before the feature stop). Rank by Impact × Confidence × Ease. Drop actions that don't fit before the feature stop, and fill gaps from the pre-mortem first.

## 4. Report

Keep it short, in this shape:

```
Judge: <task name>, <time now>, digest from <build time>

Clock
  <next deadline>: <what it needs>, <time left>
  Feature stop: <time>
  <the deadlines after it>

Problem
  <the one-line problem statement, or "can't tell from the submission">

Task fit (MoSCoW)
  Must    ✅ / 🟡 / ❌ <requirement>: <evidence or what is missing>
  Should  ✅ / 🟡 / ❌ <requirement>: ...
  Could   ...
  Won't   <what to leave out>
  Off task: <work that doesn't serve the task, or "nothing">

Mock jury (<scale>, from local/rules)
  <criterion> <weight>: <score>, <anchor it meets>, <evidence>
  ...
  Weighted: <total> / <max>   <warn if under the minimum score>

Cold read
  ✅ / ❌ what it is · how it works · how it fits the task · it runs or can be watched

Pre-mortem
  1. <likeliest reason it fails>
  2. ...
  3. ...

Submission
  ✅ / ❌ <each requirement from the documents>

Next (ICE)
  1. <action>: <criterion it lifts>, I<n> C<n> E<n> = <score>
  2. ...
  3. ...
```

Rules for the report:

- Base each score on evidence in the repo, and stay strict. A real jury doesn't give points for plans.
- After the feature stop, recommend only work on the submission, not new features.
- Watch the clock. If a deadline is less than an hour away, put it at the top as a warning, and recommend stopping feature work to submit.
- Quote the document and page for each deadline and weight, so the team can check it.

Only report. Don't edit code, commit or submit anything, unless the user asks.
