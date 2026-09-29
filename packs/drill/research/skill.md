# Identifying a tool before researching it

A brand and model line is not a subject. Resolve the attributes
that select what goes wrong *before* searching.

1. **Resolve identity before searching.**
   Read `/api/identity-keys/{pack_id}` and
   `/api/packs/{pack_id}/vocabulary` at runtime for the subject kind
   you are researching. Never hardcode the list — it goes stale
   when a new key ships.
2. **Search the discriminating attribute, not the label.**
   A model line spans years of hardware under one name.
   For cordless tools the battery platform — reused, aged, abused
   across many tools — is what teardown threads organise around.
   Search the platform or component, not the box label.
3. **Product vs family.**
   Same battery platform legitimately shares a failure pattern —
   cite one tool for another, with `component`/`stance` saying so.
   Same model name across a generation change does not.
   Never file a platform-wide claim as tool-specific.
4. **Refuse rather than guess.**
   No recoverable platform, or a name spanning generations?
   Report what is missing and what would resolve it — as an
   `unknown_subject` row is left unresearched, not aimed at
   a guessed neighbour. A confident wrong answer is worse than none.
5. **The bar is `principle.md`, in full — read it before filing.**
   Summary: keep what a second-hand buyer could not learn by handling
   the tool — model/platform-specific, predictable from age/use,
   expensive relative to the tool, consumable-and-due.
   Drop anything visible in 30 seconds (chuck play, cracked housing,
   missing clip).
