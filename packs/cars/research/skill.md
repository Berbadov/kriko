# Identifying a car before researching it

A make and model is not a subject. "Golf 7" finds a sales brochure; a buyer
already has one of those. This skill is how to turn a listing into the
attributes that actually select what is known to go wrong, before a single
search runs.

1. **Resolve the identity before searching.** Do not assume which fields
   matter — read `/api/identity-keys/cars` and the pack's own vocabulary at
   `/api/packs/cars/vocabulary` at runtime, and use whatever this
   installation currently declares. Those two calls are the only source of
   truth for what identifies a car here; a list written into this file would
   go stale the day a new identity key ships.

2. **Search the discriminating attribute, not the label.** The identity keys
   returned above are not equally useful in a query. A shared nameplate
   covers years of different hardware; the attribute that actually
   determines *how the thing fails* — the specific engine code, the specific
   gearbox code — is what a forum thread or a technical service bulletin is
   organised around. Search that. A query built only from make and model
   finds marketing copy and buyer's guides, not failure patterns.

3. **Know the difference between a claim about this car and a claim about
   its family.** Two configurations that share the discriminating attribute
   (the same engine code across two nameplates, say) legitimately share a
   failure pattern, and a finding is right to cite one for the other. Two
   configurations that share only the nameplate, with a different engine or
   gearbox underneath, do not — a finding true of one is not evidence for
   the other. Use `component` and `stance` on the finding to say which case
   you are in, and never fold a family-wide claim into a subject as if it
   were configuration-specific when it isn't.

4. **Refuse rather than guess.** If the listing under-determines the
   identity — no engine code recoverable, a model year that spans a
   generation change, a gearbox type that cannot be pinned down — do not
   pick the most common one and proceed. Report what is missing and what
   would resolve it, the same way an `unknown_subject` agenda row is left
   unresearched rather than aimed at a guessed neighbour. A wrong guess here
   is not a smaller error than no answer; it is a confident wrong answer,
   which is worse.

5. **The bar for what to keep is `principle.md`'s, not a summary of it.**
   Read it in full before filing anything:

   > Kriko surfaces the risks a used-car buyer **cannot cheaply get from a
   > standard pre-purchase inspection** (ekspertiz) — what to worry about for
   > *this* car, before they even book the expert.
   >
   > Keep a claim when it is:
   >
   > - **Specific to this configuration** — this engine code, this gearbox
   >   type, this fuel, this market. Not advice that applies to any car.
   > - **Predictable from the listing alone** — from mileage, age, fuel or
   >   gearbox, without inspecting the car. A known weak point the odometer
   >   implies.
   > - **Due unless the ad proves otherwise** — a cam belt, a major service, a
   >   clutch at high mileage. If the listing offers no evidence the work was
   >   done, that silence is itself the signal.
   > - **Expensive or dangerous** — structural failures and costly systems:
   >   emissions hardware, dual-clutch mechatronics, turbos, timing
   >   components.
   >
   > Drop a claim when it is:
   >
   > - A generic dashboard-warning-light item, or anything true of every car.
   > - Something the routine inspection already catches: fluid levels and
   >   leaks, brake-pad wear, injector bench tests, compression.
   >
   > The test: *would a buyer learn this from a normal pre-purchase
   > inspection anyway?* If yes, it is noise. *Is it specific to this car's
   > engine, gearbox or mileage, and predictable from the ad?* If yes, it is
   > why we exist.
