---
name: annsa-working
description: >
  How to work with Annsa over MCP: check you are in the right workspace,
  pick the right work, know what you may do alone, prove it shipped, and
  recover when a call fails. Use at the start of any session that reads
  or writes Annsa, and when a call is refused or times out. Generated;
  do not edit by hand.
---

# Working with Annsa

Version 3 · updated 2026-10-09. Fetch the current copy with `annsa.ask topic=working`.

Five questions, answered from the replies — never guessed.

## 1. Am I in the right workspace?

Every reply carries `who`. Read it before your first write.

- `who.environment` and `who.host`: `production · app.annsa.ai` is the live customer account; `staging · canopy.annsa.ai` is not. A number like #124 names a different row in each.
- `who.workspace.name` and `who.workspace.id`: the workspace this call ran in. `who.actor.email` is there on a person's own sign-in.
- `who.actor.kind`: `user` is a person's credential, `agent` is yours. Some verbs are a person's only (below).
- Wrong workspace or environment: stop before any `annsa.act`. Say which one you are on and which one you expected.
- A new or empty workspace: `annsa.ask topic=welcome` first.

## 2. What should I work on?

- `annsa.priorities` is the ranked list of active work (open, ready, building). `total` is how many match; `returned` is this page. Page with `limit` (max 100) and `offset`.
- A row's `next_action` says what waits on an agent. `owner` and the spec's holder say who has it.
- `annsa.priorities mine=true` is what you hold. Empty means you hold nothing, not that nothing exists.
- One bet: `bet=<id>`. The proposal inbox: `bet=unplaced`. Parked work is hidden unless `include_parked=true` — do not pick it up.
- A person's explicit instruction beats the ranking.
- Someone else holds it: leave it. `claim takeover=true` needs a reason and is for when they cannot hand it off.
- Start with `annsa.spec priority_number=N`, then `annsa.act claim`.

## 3. What may I do on my own?

**Reads change nothing:** `annsa.priorities`, `annsa.spec`, `annsa.ask` (including `do_we_have`).

**`annsa.act` always writes.** What each one touches:

- `submit` lands a feedback row; with `stand_alone=true` it proposes a new priority (Unplaced until a person places it).
- `claim` / `release` / `handoff`: who holds the work.
- `write`: one section of a spec you hold. `note`: what you did or found.
- `verify`: a receipt for one Done When line. `ship`: records completion — it does not deploy.
- `merge` retires numbers for good.
- A person's only — an agent credential is refused these: `adjudicate`, `answer`, `ask_back`, `assign`, `import_direction`, `park`, `release_findings`, `retract`, `share`, `sign`, `transcript`. That includes `share`, which tells customers; an email cannot be unsent. An agent may use these only in part: `bet` (list), `correct` (detail, ruled_out, title), `direction` (get, list, update), `principle` (propose). Agents may list bets and `place` priorities on them; creating, reordering, retitling and deleting bets stay with a person. An agent's `severity` is a proposal until a person types the P.

**Before you write, read what a person already decided.** `annsa.spec` returns:

- `decision`: an ask and its answer. Answered means apply it.
- `authority`: `may_decide` is yours to settle; `must_come_back` goes to a person.
- `principles`: rules that reach this priority. A settled topic is not asked again.
- `answered` on any reply means a person answered your ask: apply it now. `claim` returns `principles` and `related_answers`; read them before you ask.
- Read `learned` on claim before you start; it's what earlier agents found out.

Settle anything else yourself and carry on. Escalate (`annsa.act escalate`, see `annsa.ask topic=decisions`) only when the question changes scope, affects customers or irreversible data, contradicts a principle, or is a choice between real options. Raising one does not block your other work.

**New work:** Before submit stand_alone, ask annsa.ask do_we_have with the words. If it answers same #N, attach with priority_number=N instead of adding a priority. If it answers possibly #N, read #N first: attach if it is the same problem, otherwise submit stand_alone.

**Root cause:** Name the root cause in one line when you file: When ___, ___ can't ___ because ___. It's what matching compares.

**PRs:** Recommended: one priority, one PR, one ship. Work that needs more than one PR is more than one priority: file the parts as sub-priorities under it (`annsa.act submit stand_alone=true parent=N`), each with its own PR and its own ship. If `annsa.spec` returns a principle that says otherwise for this workspace, the principle wins. Put `Annsa-Spec: <spec id>` in the PR body and send `pr_url` on `claim` or `note`.

## 4. How do I prove it worked?

Merged is not deployed, deployed is not verified, verified is not confirmed by the customer. Say which one you have.

- Check every Done When line against the live system, not the code.
- Record each with `annsa.act verify spec_id=… done_when_index=N how=… where=…`. `where` must be followable: a test node id, a URL, a thread. Prose is refused.
- A line you could not check stays unchecked, and you say so.
- `ship` after the checks, with `pr_url`, and `learned` when there is something the next spec should know. `share` is separate.
- Releasing to production is a person's decision. Follow the workspace's rule for deploys, and never release to production on your own.

## 5. What do I do when a call fails?

- **Unauthorized / Authentication required:** the client has no working sign-in. Tell the person to reconnect Annsa in the client's MCP settings. Do not loop the same call.
- **Invalid or expired token:** the same. A new sign-in, not a retry.
- **Refused write:** read the reply. It names the reason and often the fix (a missing field, a person-only verb, a section that is not yours). Change the call; never resend it unchanged.
- **Held by someone else:** the reply names the holder. Ask them to hand off, or work on something else.
- **Timed out or no reply:** the write may have landed. Read it back first (`annsa.spec` or `annsa.priorities priority_number=N`), then retry only what is missing.
- **Filed as a repeat:** `submit` keys a finding by `path`, `rule` and `line`. A `path` with no `line` matches any earlier row on that file — leave `path` out unless you have the line, and name the file in the words.
- **Attached to #N, or may_be #N** on a new priority: a filing is never refused. Read #N. If a new priority is the same as #N, `annsa.act merge into=N`. If it was attached to the wrong row: under a person's sign-in, retract it there and send it again with `insist=true`; under an agent credential, which is refused `retract`, `note` on the wrongly attached row what the mistake is and ask the person to move it.
- **Tools missing in the client:** most clients load MCP servers when a session starts. A server added mid-session needs a new session.

## Examples

**Customer-backed work.** `annsa.priorities` → #20 ranks 3rd, 4 people, nobody holds it. `annsa.spec priority_number=20` → the quotes, people and companies as `evidence`. `annsa.act claim` → yours; write all five sections from it. Build; open one PR with the `Annsa-Spec` trailer; `note pr_url=…`. After the person deploys: `verify` each Done When line with a URL, then `ship`.

**A finding with no quotes.** You hit a bug. `annsa.ask do_we_have="…" kind=finding` → `different`. `annsa.act submit stand_alone=true with_spec=true severity=1 severity_reason="…"` → #652 proposed, Unplaced, spec minted. Claim it; you write all five sections, Problem and Evidence from what you observed.

**A blocked decision.** The fix could warn staff or block the booking. `annsa.spec` has no principle that settles it. `annsa.act escalate trigger=options` with the three-line ask and options A and B. Carry on with the tests. When `annsa.spec` returns `decision` answered, apply it.

**A failed verification.** Done When line 2 fails on staging. Do not `verify` it and do not `ship`. `note` what you saw, with the URL; fix, reopen a PR, and check again after the next deploy.

## Where the rest lives

- `annsa.ask topic=spec-skill`: how to write your part of a spec.
- `annsa.ask topic=decisions`: how to ask a person and apply the answer.
- `annsa.ask topic=welcome`: where a new workspace starts.
- `annsa.ask about=annsa`: anything about the product.
