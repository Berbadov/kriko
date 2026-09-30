/** Which vendor's mark goes beside a name (B175, D2).
 *
 * The name is data the API already returns: a harness id (`claude-code`), a
 * LLM the CLI listed (`claude-sonnet-4`, `openai/gpt-5`, `gemini-2.5-pro`).
 * The mark is read off that text, so an LLM released tomorrow by a vendor
 * already listed here gets its mark with no registration step, and one by a
 * vendor not listed gets the plain generic mark rather than a wrong one.
 *
 * A closed vocabulary of this app's own integrations, never of a pack: no
 * catalog names one of these (`test_ui_contains_no_pack_vocabulary`).
 *
 * Ordered, first match wins: `opencode` and `copilot` are harnesses that run
 * other vendors' LLMs, and their own id must win over an LLM name that
 * happens to follow it.
 */
export type MarkId =
    | "anthropic"
    | "google"
    | "openai"
    | "mistral"
    | "github"
    | "opencode"
    | "generic";

const FAMILIES: [RegExp, MarkId][] = [
    [/opencode/, "opencode"],
    [/copilot|github/, "github"],
    [/claude|anthropic|sonnet|opus|haiku/, "anthropic"],
    [/gemini|antigravity|agy\b|google|gemma/, "google"],
    [/gpt|openai|codex|\bo[134]\b|chatgpt/, "openai"],
    [/mistral|vibe|codestral|devstral|magistral/, "mistral"],
];

export function markFor(text: string | undefined | null): MarkId {
    const name = String(text ?? "").toLowerCase();
    if (!name) return "generic";
    for (const [pattern, id] of FAMILIES) if (pattern.test(name)) return id;
    return "generic";
}
