---
name: annsa-spec
description: >
  How an agent writes an Annsa spec over MCP. Use when you hold a priority and
  need to write its sections from the evidence annsa.spec returns; when a
  write is refused; or when a spec carries updates to approve. Generated — do
  not edit by hand.
version: 1.0.0
updated: 2026-10-14
---

# Writing a spec

If your saved copy's version is older, replace it.

A spec has five sections and starts with all five empty. Annsa supplies the evidence; you write every section.

| Section | Who writes it | What it is |
|---|---|---|
| Problem | the holder, a person | The single problem being solved. Observable and solution-free. |
| Signals and direction | the holder, a person | The evidence-backed reading of the rows, by kind: people and paying customers are evidence, findings are what is broken, ideas are proposals. |
| What to build | the holder, a person | The current direction to the agent. Changes here create a material spec version. |
| Files to touch | the holder, a person | Verified paths when known; otherwise named code areas explicitly marked unverified. |
| Done When | the holder, a person | Given a state, when an act, then an observable — one line each, individually verifiable. Each line can receive its own receipt, so the lines must not be reworded once receipts point at them. |

**Who decides:** you write Problem, Signals and direction, What to build, Files to touch, Done When while you hold the priority. Annsa writes none of them: `annsa.spec` returns the priority's `evidence` as data (each quote with its person, company, revenue band, source and date), and you write from it. Write what the evidence says, never what you imagine. A person can write anywhere, and a person's words are never overwritten.

## Naming a priority

A title says what becomes true for the customer or builder, in words they would use, nine words or fewer. The mechanism goes in What to build. Test: read it on the board and know whether you want it without opening it; could you say it to a customer in these words?

| Not this | This |
|---|---|
| A submit queues a pipeline that re-places rows the door already attached | Feedback stays where you or your agent put it |
| A shipped spec is never rewritten: a change of kind after ship is a reading for the next spec | A shipped spec never changes after it ships |
| Answer an ask over MCP: a person who sees the decision in a terminal can give it there | Answer your agent's question from your terminal |

The door nudges when a title carries an engine word or runs past 90 characters; the row lands either way. The same rule shapes the spec: The problem is what the person experiences; What to build opens with the outcome; Files to touch and Done When carry the mechanism.

**Filing a finding:** Send `severity` (P0–P3) with a one-line `severity_reason` on every finding. A finding ranks by severity first and has no account spread or revenue to fall back on, so one without a severity sits at the bottom of the board. A person's severity always wins.

**Root cause:** Name the root cause in one line when you file: When ___, ___ can't ___ because ___. It's what matching compares.

**Adding a priority:** Before submit stand_alone, ask annsa.ask do_we_have with the words. If it answers same #N, attach with priority_number=N instead of adding a priority. If it answers possibly #N, read #N first: attach if it is the same problem, otherwise submit stand_alone. One problem is one priority, and one priority is one PR: work that needs more than one PR is split into sub-priorities under it (submit stand_alone with parent=N), each with its own PR. A workspace principle that says otherwise wins. Pick the theme from the list the reply gives you.

## Writing it

Write like a product builder talking to another one. Three or four sentences a section. Name the fact, a number, a file, a row id, when it is the fact; leave out the mechanism tour. No essays, no AI cadence. Could you say it to a customer in these words?

The register:

- we were not checking for similar features with the cosine set at .22 and we lifted it to 0.75 to test
- positive gets sent, negative didn't send
- the email doesn't link to the priority or the message sent too
- there is no toast to confirm the decision and it's not instant
- all the git titles at the moment read like riddles to me

| Not this | This |
|---|---|
| One signal, read in code, not inferred. backend/services/clustering.py cluster_feedback: after labels are assigned, `elif noise_indices and not topic_clusters:` builds topic_clusters[0] from every noise row. That branch exists for the nightly full-corpus run, but the mini buffer calls the same function through get_focused_clusters, and in the mini buffer two or three rows is the ordinary case, so "all noise" is not an edge there, it is most runs. | With only a few pieces of feedback, the clusterer always answers "no groups". A fallback then grouped everything it rejected into one priority without checking similarity. |
| fix(clustering): two pieces of feedback that do not agree never become one priority | Stop merging unrelated feedback into one priority (#348) |

A PR title says what changed, verb first, in one line a person can read in the list — "Stop merging unrelated feedback into one priority (#348)". The what-becomes-true form is for the priority's title on the board, not the PR.

The door nudges when a section runs past 120 words or reads like AI; the text lands either way.

## Write

**When**

- [ ] You hold the priority: `annsa.work claim priority_number=N label="<your session>"`. Send `label` once, on your first call of the session; the seat sticks (`who.actor.seat` confirms it).
- [ ] Claim BEFORE you touch code — before the branch, before the first edit. Claiming mints the spec if there is none, so there is nothing to build first; until you claim, the board shows nobody on the work.
- [ ] You have read the whole spec first: `annsa.spec priority_number=N` — its `evidence`, and `updates` if it carries any.
- [ ] Read `learned` on claim before you start; it's what earlier agents found out.

**The shape**

- Problem: yours. Observable and solution-free: what the person experiences, not what to build.
- Signals and direction: yours. The reading of the rows by kind; with no quotes it opens with No evidence found. and says what you observed after it.
- What to build: yours. Opens with the outcome, then the direction. Never the placeholder.
- Files to touch: yours. One path per line, verified in the repo and marked (new|modify), or the word Unverified.
- Done When: yours. One line each: Given a state, when an act, then an observable. A test, a URL or a person can check it.
- `write` replaces the whole section. To add a line, send the section as it stands with the line added.
- Files to touch lines are `path (new|modify)`, or carry the word Unverified. Never guess a path.
- With no quotes on the priority, Signals and direction opens with No evidence found. and says what you observed after it.

**The call**

- [ ] `annsa.work write section=the_problem text="…"` — The single problem being solved. Observable and solution-free.
- [ ] `annsa.work write section=signals_and_direction text="…"` — The evidence-backed reading of the rows, by kind: people and paying customers are evidence, findings are what is broken, ideas are proposals.
- [ ] `annsa.work write section=what_to_build text="…"` — The current direction to the agent. Changes here create a material spec version.
- [ ] `annsa.work write section=files_to_touch text="…"` — Verified paths when known; otherwise named code areas explicitly marked unverified.
- [ ] `annsa.work write section=done_when text="…"` — Given a state, when an act, then an observable — one line each, individually verifiable. Each line can receive its own receipt, so the lines must not be reworded once receipts point at them.

No quotes on the priority — a dogfood row, or a row a reviewer filed from a PR? Then the finding IS your evidence.

**What happens next**

- [ ] The spec is versioned, then your text replaces that one section; the reply says `written: true` and the version number.
- [ ] Your writes in one sitting are ONE version: the same seat writing again within 30 minutes updates that version rather than adding another. A different seat, a person's edit or a refresh starts a new one.
- [ ] If two writers raced, the reply says so and nothing was written — read the spec again and resend.

**What not to do**

- Do not take over a seat someone holds. `note` what you found, or ask them to `handoff`.
- Do not send one line to a section that has more. `write` replaces the whole section.
- Do not write what you imagine. No quotes means Signals and direction opens with the words `No evidence found.` and says what you observed after it.

## When a write is refused

**When**

- [ ] The reply says `written: false, proposed: true` and carries a `reason`.

**The shape**

Two reasons, and the door names which:

- "not the holder" → someone else holds the priority, or nobody does.
- "someone wrote this" → a person's, or another agent's, words are never overwritten.

**What happens next**

- [ ] Your text is recorded as an **update** on that section, with the reason. Nothing is lost.
- [ ] "not the holder" → claim it, or `note` your text for whoever holds it.
- [ ] "someone wrote this" → say in your `note` which update to approve, and carry on.

**What not to do**

- Do not resend the same write. The answer will be the same; the update is already there.
- Do not `note` that you changed the section. You did not; the update is pending.

## Updates on a spec

**When**

- [ ] `annsa.spec` carries `updates` — absent when there are none; an absent key means nothing to do.

**The shape**

Each update: `id`, `section`, `reason`, `proposed_text`, `previous_text`, `proposed_by_label`, `at`. Oldest first.

**The call**

- [ ] If you are the section's author right now (you hold it, and it is yours to write): `annsa.decide approve update_id=<id>` or `annsa.decide dismiss update_id=<id>`.

**What happens next**

- [ ] Approve: the spec is versioned, then exactly the proposed text replaces that one section.
- [ ] Dismiss: the current text stays. Not delete — the update stays as history.
- [ ] A decision stays. Deciding again is refused, not re-decided.

**What not to do**

- Do not decide an update on a section you may not write. Leave it; a person decides.
- Do not approve your own refused write from another seat. Same rule.

## When you stop

**The call**

- [ ] `annsa.work note text="…"` — what you did, what is next, in your own words.
- [ ] `annsa.work release reason="…"` — if you are not finishing.
- [ ] A reviewer's finding that is NOT a bug? `annsa.work release reason="not a bug: <why>" verdict=false_positive` — your reason becomes a note and a person is asked to dismiss. Never close a finding yourself; a false positive is a claim too.
- [ ] `annsa.work ship` only after the agreed checks pass.
- [ ] `learned="…"` on that ship: what you found out building it, in a sentence or two. It lands as an idea on the same priority, for the next spec written there. Nudged, not required.

**What not to do**

- Do not leave a seat you are not in. Release it.
- Do not call it shipped because you are done. Shipped means merged and checked.

## Changes

- 1.0.0 (2026-10-14): Versioned.
