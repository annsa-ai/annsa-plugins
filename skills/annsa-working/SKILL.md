---
name: annsa-working
description: >
  How to work with Annsa over MCP: check you are in the right workspace,
  pick the right work, know what you may do alone, prove it shipped, and
  recover when a call fails. Use at the start of any session that reads
  or writes Annsa, and when a call is refused or times out. Generated;
  do not edit by hand.
version: 5.6.0
updated: 2026-10-19
---

# Working with Annsa

If your saved copy's version is older, replace it. `annsa.ask topic=working` has the current one.

Six questions, answered from the replies — never guessed.

## 1. Am I in the right workspace?

Every reply carries `who`. Read it before your first write.

- `who.environment` and `who.host`: `production · app.annsa.ai` is the live customer account; `staging · canopy.annsa.ai` is not. A number like #124 names a different row in each.
- `who.workspace.name` and `who.workspace.id`: the workspace this call ran in.
- `who.actor.kind`: `user` is a person's credential, `agent` is yours.
- Send `label` on your first call. It names your seat on the board for the whole connection, and `who.actor.seat` confirms it. If several agents share one connection, send `label` on every write.
- Wrong workspace or environment: stop before any write and say which one you are on.
- A new or empty workspace: `annsa.ask topic=welcome` first.

## 2. What should I work on?

- `annsa.priorities` is the ranked list of active work; a row's `next_action` says what waits on an agent. `mine=true` is what you hold.
- One bet: `bet=<id>`. The proposal inbox: `bet=unplaced`. Parked work is hidden unless `include_parked=true` — do not pick it up.
- A person's explicit instruction beats the ranking.
- Someone else holds it: leave it. `claim takeover=true` needs a reason and is for when they cannot hand it off.
- A ticket, issue or story: find its priority first (`annsa.priorities topic=…`), then read `annsa.spec`. Do not write a spec from the repo or the ticket alone. No matching priority means the work may not be customer-driven: say so.
- "Did it work?" with nothing named: `annsa.spec batch=true status=shipped`. An empty list is the answer: nothing has shipped.

## 3. What may I do on my own?

`annsa.priorities`, `annsa.spec` and `annsa.ask` only read. **Writes go through five tools**; `annsa.act` is their old single name and still takes every action.

- `annsa.work`: claim, write one section of a spec you hold, note, verify a Done When line, escalate an ask, hand off or release (with `next_action` and `ruled_out`), ship. Releasing is not closing: work that will not be done is a person's dismiss.
- `annsa.file`: submit feedback or a finding, or propose a priority (section 4).
- `annsa.decide`: propose a principle.
- `annsa.board`: merge (it retires numbers for good), place on a bet, correct a title, propose a severity.
- `annsa.share`: tells customers. An email cannot be unsent; a wrong one is fixed with a correction.
- A person's only — an agent credential is refused these: `adjudicate`, `answer`, `ask_back`, `assign`, `import_direction`, `park`, `release_findings`, `retract`, `share`, `sign`, `transcript`. An agent may use these only in part: `bet` (list), `correct` (detail, ruled_out, title), `direction` (get, list, update), `principle` (list, propose). An agent's `severity` is a proposal until a person types the P; quote it as proposed.

**Before you write, read what a person already decided.** `annsa.spec` returns:

- `decision`: an ask and its answer. Answered means apply it.
- `authority`: `may_decide` is yours to settle; `must_come_back` goes to a person.
- `principles`: rules that reach this priority. A settled topic is not asked again.
- `claim` returns `principles`, `related_answers` and `learned` (what earlier agents found out): read them before you start or ask. `answered` on any reply means a person answered your ask: apply it now.

Settle anything else yourself and carry on. Before you escalate, ask `annsa.ask` whether it is already settled: a question the docs or a principle answer is yours to settle. Escalate (`annsa.work escalate`, see `annsa.ask topic=decisions`) only when the question changes scope, affects customers or irreversible data, contradicts a principle, or is a choice between real options. Customer revenue or personal data in what you build counts. Raise it, then carry on with the safest option while you wait: raising one does not block your other work.

**PRs:** Recommended: one priority, one PR, one ship. Work that needs more than one PR is more than one priority: file the parts as sub-priorities (`annsa.file submit stand_alone=true parent=N`). A workspace principle that says otherwise wins. Write Done When before you open the PR: a PR on an empty one merges with nothing to verify, and its reply says so. Put `Annsa-Spec: <spec id>` in the PR body and send `pr_url` on `claim` or `note`.

## 4. How do I add work?

- **Ask first:** Before submit stand_alone, ask annsa.ask do_we_have with the words. If it answers same #N, attach with priority_number=N instead of adding a priority. If it answers possibly #N, read #N first: attach if it is the same problem, otherwise submit stand_alone.
- **Root cause:** Name the root cause in one line when you file: When ___, ___ can't ___ because ___. It's what matching compares.
- **An idea or a finding.** An idea is something that could be better: `annsa.file submit stand_alone=true signal_class=idea`. A finding is something you saw break or fall short: `signal_class=agent`, or `dogfood` when you hit it using the product. `adopt_priority` is the old name for submit stand_alone.
- **Every finding** carries `severity` (P0–P3), a one-line `severity_reason` and `root_cause`. One without a severity sits at the bottom of the board.
- `with_spec=true` mints a spec too: for a detail that already holds the evidence and a direction, not for a bare title.
- **Proposals land Unplaced unless you name a bet.** Send `bet` (its title or id) with stand_alone to put a new priority on it; it stays proposed until a person signs or moves it. A goal is a bet, and a person creates it: propose a goal in words.

**"Look at this project and propose work."** Read the code and the person's recent work. List at most five, each checked with `do_we_have`, and file only the ones the person says yes to, as an idea or a finding. Tell the person they wait in `annsa.priorities bet=unplaced` until they place them.

## 5. How do I prove it worked?

Merged is not deployed, deployed is not verified, verified is not confirmed by the customer. Say which one you have.

- Check every Done When line against the live system, not the code.
- Record each with `annsa.work verify spec_id=… done_when_index=N how=… where=…`. `where` must be followable: a test node id, a URL, a thread. Prose is refused.
- A line you could not check stays unchecked, and you say so. A line that fails: no `verify`, no `ship`; `note` what you saw with the URL, fix it, and check again after the next deploy.
- `ship` after the checks, not on merge, with `pr_url` and any `learned`.
- Releasing to production is a person's decision. Follow the workspace's rule for deploys.

## 6. What do I do when a call fails?

- **Unauthorized, Authentication required, or an invalid or expired token:** the client has no working sign-in. Tell the person to reconnect Annsa in the client's MCP settings. A retry will not fix it.
- **Refused write:** read the reply. It names the reason and often the fix (a missing field, a person-only verb, a section that is not yours). Change the call; never resend it unchanged.
- **Timed out or no reply:** the write may have landed. Read it back first (`annsa.spec` or `annsa.priorities priority_number=N`), then retry only what is missing.
- **Filed as a repeat:** `submit` keys a finding by `path`, `rule` and `line`. A `path` with no `line` matches any earlier row on that file — leave `path` out unless you have the line, and name the file in the words.
- **Attached to #N, or may_be #N** on a new priority: read #N. The same problem: `annsa.board merge into=N`. Attached to the wrong row: a person retracts it there and sends it again with `insist=true`; an agent, refused `retract`, notes the mistake on that row and asks the person to move it.
- **Tools missing:** most clients load MCP servers at session start; a server added mid-session needs a new session.

## Example

**Customer-backed work.** `annsa.priorities` → #20 ranks 3rd, 4 people, nobody holds it. `annsa.spec priority_number=20` → the quotes, people and companies as `evidence`. `annsa.work claim` → yours; write all five sections from it. Build; open one PR with the `Annsa-Spec` trailer; `note pr_url=…`. After the person deploys: `verify` each Done When line with a URL, then `ship`.

## Where the rest lives

- `annsa.ask topic=spec-skill`: how to write your part of a spec.
- `annsa.ask topic=decisions`: how to ask a person and apply the answer.
- `annsa.ask about=annsa`: anything about the product.

## Changes

- 5.6.0 (2026-10-19): Name a bet with stand_alone to put a new priority on it.
- 5.5.0 (2026-10-15): Check annsa.ask before escalating; escalate only what it leaves open.
- 5.4.0 (2026-10-15): Write Done When before you open the PR.
