# Identifying a car before researching it

A make and model is not a subject. "Golf 7" finds a brochure;
a buyer already has one. Resolve the attributes that select
what goes wrong *before* searching.

1. **Resolve identity before searching.**
   Read `/api/identity-keys/cars` and `/api/packs/cars/vocabulary`
   at runtime and use what this installation declares.
   Never hardcode the list — it goes stale when a new key ships.
2. **Search the discriminating attribute, not the label.**
   A nameplate spans years of hardware; engine and gearbox codes
   are what forum threads and bulletins organise around.
   Make + model alone finds marketing, not failure patterns.
3. **Car vs family.**
   Same engine code across two nameplates can share a pattern —
   cite one for the other, with `component`/`stance` saying so.
   Same nameplate with a different engine/gearbox underneath cannot.
   Never file a family-wide claim as configuration-specific.
4. **Refuse rather than guess.**
   Listing under-determines identity (no engine code, year spanning
   a generation change, unpinned gearbox)? Report what is missing
   and what would resolve it — as an `unknown_subject` row is left
   unresearched, not aimed at a guessed neighbour.
   A confident wrong answer is worse than none.
5. **The bar is `principle.md`, in full — read it before filing.**
   Summary: keep what a buyer cannot cheaply get from ekspertiz —
   config-specific, predictable from the listing,
   due-unless-proven-otherwise, expensive/dangerous.
   Drop generic warning-light items and anything the routine
   inspection already catches.
