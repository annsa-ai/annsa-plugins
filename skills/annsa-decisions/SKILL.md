---
name: annsa-decisions
description: >
  The loop for a question only a person can answer: raise it as a three-line
  ask with `annsa.act escalate`, read the answer back on `annsa.spec`, answer a
  question a person sends back, apply the decision to the spec. Use when a
  question changes scope, affects customers/revenue/security/irreversible data,
  contradicts a principle, or needs a choice between legitimate options. Not for
  anything you can settle from existing direction. Generated — do not edit
  by hand.
---

# Decisions

An ask puts a priority in a person's **Needs you** queue. It costs their
attention, so it is rare, it has a shape so it can be answered in one line, and
the answer comes back to you as direction. Really simple language. No essays.

**Who decides:** a person answers; you raise, read and apply. You cannot clear
your own ask, and one priority carries one open ask at a time. A person answers
from the board, or from their own terminal with `annsa.act answer` (and asks
you something back with `annsa.act ask_back`).

**When the person is in your terminal (#796):** ask them, then relay their
exact words: `annsa.act answer priority_number=N person_words="<their words>"
person=<their email>`. It is recorded as their answer, via your seat, on this
priority only. The same works for `annsa.act severity`: their P, typed as theirs.
Never answer in your own words, never name someone who is not a member, and
`ask_back` and `sign` stay theirs. If the workspace answers in the app only,
the door says so: hand them the `url` instead.

## Raise

**When**

- [ ] It is one of the four triggers. If not, it is a note — `annsa.act note` and carry on.
  - **scope** — Changes scope or intended outcome
  - **customers** — Affects customers, revenue, security or irreversible data
  - **principle** — Contradicts a principle
  - **options** — Requires choosing between legitimate product options
- [ ] Nothing on the spec already settles it. `annsa.spec` first — an answered `decision` there is direction, not a question.
- [ ] No ask is already open on the row (`decision.state == "open"`). A person answers one question at a time.

**The shape**

Three questions, in order:

1. **Which kind?** `decision | help | gap | update`. A *decision* carries options, as short labels, with the one you'd take.
2. **What is the ask, in one line?** A person should be able to answer it in one line.
3. **What principle, if the person stated it, would let an agent settle this next time?** That is `principle` — the line agents skip and the one that matters. An ask without it is an ask they will get again.

- `topic` — one line — what this is about
- `kind` — decision | help | gap | update
- `ask` — the ask itself, one line
- `options` — short labels, only for a decision — "A - human only", "B - agent and human" *(optional)*
- `recommend` — which option you'd take, by its letter — optional
- `principle` — the rule that would let an agent settle this next time — it invites the rule, not a sentence about the agent

An example — this is the register:

```
Topic: Needs-you flag
Ask: Decision on who can clear it or if it can't be exited
Options: A - human only  B - agent and human  C - can't be removed
Principle - product decision
```

**The call**

```
annsa.act escalate
  priority_number: <#0NN>
  trigger:   options
  topic:     "Needs-you flag"
  kind:      decision
  ask:       "on who can clear it or if it can't be exited"
  options:   ["A - human only", "B - agent and human", "C - can't be removed"]
  recommend: "A"
  principle: "product decision"
```

**What happens next**

- [ ] The priority shows in **Needs you** on the board and the ask sits above the brief until a person answers.
- [ ] Raising does not block you. Carry on with anything that does not depend on the answer.
- [ ] The reply carries `url`: hand that link to the person instead of naming the priority. It opens the sheet on the open decision, options ready to tap. `annsa.spec` carries the same `url` on an open `decision`, and `annsa.priorities mine=true` on a `needs_me` question back.
- [ ] If the door refuses the shape, the reply shows the shape and an example — fix and resend.

**What not to do**

- Do not narrate. A topic is a line; an option is a label; a principle is a rule, not a paragraph.
- Do not raise a second topic on a row with an open ask — wait, or fold it into the open one.
- Do not raise what you can settle from the spec, a note, or a principle already written.

## Read back

**When**

- [ ] Every time you pick a priority up: `annsa.spec priority_number=N` and read `decision` before you write.

**The shape**

`decision` is absent when nothing was ever asked — like `updates`, which is absent when none are pending; read both keys, an absent key means nothing to do. Otherwise:

- `state: open` — `ask`, `lines`, `since`, and `question_back` if a person asked you something.
- `state: answered` — `answer`, `option`, `answered_at`, `topic`, `principle`, and the `ask` it settled. `relay` is set when an agent carried the person's words: `name`, `via`, `quote`.

The answer's fields:

- `text` — what the person wrote
- `option` — the option they chose, by its label — only if the ask had options
- `kind` — answer | ask_back — ask_back is a question back to you; the ask stays open
- `by` — the user id who answered
- `at` — when

The same record is a note on the priority, titled by kind — decision: *Decision made*, help: *Help given*, gap: *Gap answered*, update: *Update acknowledged* — e.g. `Decision made — Needs-you flag: A - human only`.

**What happens next**

- [ ] `answered` on any reply → a person answered your ask: apply it now. On `claim`, read `principles` and `related_answers` before you ask.
- [ ] `answered_at` after your last note → the direction changed while you were away. Apply it (below) before anything else.
- [ ] `question_back` set → answer it (below).
- [ ] `state: open` and it is your ask → carry on with what does not depend on it.

**What not to do**

- Do not treat an open ask as an answer. Open means nobody has decided.
- Do not re-ask an answered question. The answer stays on the row until a new ask replaces it.

## Answer a question back

**When**

- [ ] `decision.question_back` is set, or a note titled `Question for the agent — <topic>` appeared. The person wants more before deciding; the ask is still open.

**The shape**

The same three-line ask, rewritten with what they asked for — the **same topic**, a better `ask`, better options. Not a reply thread.

**The call**

```
annsa.act escalate          # same topic → updates the open ask
  priority_number: <#0NN>
  topic:     "Needs-you flag"   # unchanged
  ask:       "<the ask, with what they asked for>"
  ...
```

If what they asked for is context that does not change the ask, `annsa.act note` it and leave the ask as it is.

**What happens next**

- [ ] The open ask is replaced; the question back is consumed; the person sees the new ask in the same place.
- [ ] Their question stays on the priority as the note `Question for the agent — Needs-you flag`.

**What not to do**

- Do not change the topic. A new topic is a second question and the door refuses it while one is open.

## Apply

**When**

- [ ] `decision.state == "answered"` and the answer changes what you would build.

**The shape**

The section as it stands, plus one line quoting the decision: *"Decision (12 Sep): A - human only — <their words>."* The principle goes with it if they gave one, so the next agent does not ask again. `write` REPLACES the section with what you send — so send the current text with the line added, never the line alone.

**The call**

- [ ] `annsa.spec priority_number=N` — copy the section's current text.
- [ ] Your section (you hold the priority): `annsa.act write section=what_to_build text="<current text, then a blank line, then> Decision (<date>): <option> — <their words>. Principle: <principle>"`.
- [ ] Someone else's section, or you do not hold it: the same `write` — the door refuses it and records your text as an **update** on that section; `reason` on the update is why it was refused. Nothing is lost.
- [ ] Then `annsa.act note text="Applied: <topic> → <option>. Changed: <section>."` — one line.

**What not to do**

- Do not send the decision line alone. `write` replaces the whole section; the rest of the direction would be gone.
- Do not paraphrase the answer. Quote it.
- Do not mark anything shipped because a decision was made. Shipped means merged and checked.
