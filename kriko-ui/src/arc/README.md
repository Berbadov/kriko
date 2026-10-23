# Arc components

Source copied from [UIArc](https://uiarc.dev) (MIT, free tier), fetched on
2026-10-24 from its registry (`https://uiarc.dev/r/<name>.json`):
`button`, `textarea`, `checkbox`, `accordion`, `file-upload`, and
`registry/motion-tokens.ts` as `lib/motion-tokens.ts`.

The files are the library's own and are meant to be owned: change them here,
not by re-fetching. To add another, fetch its registry JSON and place its
`tsx` and `module.css` in a folder of its own name.

`arc.css` answers the CSS variables the components read from Kriko's tokens
(`../styles/tokens.css`). Arc's own `foundation.css` is not used: it sets a
global focus outline with `!important` and has its own theme switch.

What is used where:

| Component | Where |
|---|---|
| `Textarea` | Catalogs, the catalog to research |
| `Checkbox` | Logs, the model store |
| `Accordion` (through `ui/Disclosure.tsx`) | Setup, Local model, Agents, Catalogs |
| `FileUpload` | Backups, restore |
| `Button` | not used yet |
