# Identifying a tool before researching it

A brand and model line is not a subject. This skill is how to turn a listing
or a product page into the attributes that actually select what is known to
go wrong, before a single search runs.

1. **Resolve the identity before searching.** Do not assume which fields
   matter — read `/api/identity-keys/{pack_id}` and this pack's own
   vocabulary at `/api/packs/{pack_id}/vocabulary` at runtime, and use
   whatever this installation currently declares for whichever subject kind
   you are researching. Those two calls are the only source of truth here; a
   list written into this file would go stale the day a new identity key
   ships.

2. **Search the discriminating attribute, not the label.** A model line
   spans years of hardware sold under one name; the attribute that actually
   determines *how the thing fails* is usually not the model at all. For a
   cordless tool the battery platform it takes — not the drill's own model
   line — is what a teardown thread or a forum complaint is organised
   around, because the platform is what gets reused, aged, and abused across
   many tools. Search the platform or the component, not the label on the
   box.

3. **Know the difference between a claim about this product and a claim
   about its family.** Two tools built on the same battery platform
   legitimately share that platform's failure pattern, and a finding is
   right to cite one for the other. Two tools that share only a model name
   across a generation change do not. Use `component` and `stance` on the
   finding to say which case you are in, and never fold a platform-wide
   claim into a subject as if it were specific to one tool when it isn't.

4. **Refuse rather than guess.** If the listing under-determines the
   identity — no recoverable battery platform, a model name that spans more
   than one hardware generation — do not pick the most common one and
   proceed. Report what is missing and what would resolve it, the same way
   an `unknown_subject` agenda row is left unresearched rather than aimed at
   a guessed neighbour. A wrong guess here is not a smaller error than no
   answer; it is a confident wrong answer, which is worse.

5. **The bar for what to keep is `principle.md`'s, not a summary of it.**
   Read it in full before filing anything:

   > Keep a claim when it tells a second-hand buyer something they could not
   > learn by picking the tool up in a shop:
   >
   > - **Specific to this model or battery platform** — not "cordless drills
   >   wear out".
   > - **Predictable from age or use** — cycles on the pack, hours on the
   >   motor.
   > - **Expensive relative to the tool** — a dead battery platform or a
   >   stripped gearbox matters; a scuffed case does not.
   > - **Consumable and due** — brushes on a brushed motor, at a stated
   >   interval.
   >
   > Drop anything visible in thirty seconds of handling: play in the chuck,
   > a cracked housing, a missing belt clip.
