/* The designed motion values, held to the sheets they live in.
 *
 * `Motion.md` in the design system names each timing. This pins the ones the
 * app shows to `tokens.css`, and the animations that read them to those
 * tokens, so a retuned number is a test change and not a silent drift.
 */
import { describe, expect, it } from "vitest";

const SHEETS = import.meta.glob("./**/*.css", {
    query: "?raw",
    import: "default",
    eager: true,
}) as Record<string, string>;

const tokens = SHEETS["./tokens.css"];
const components = SHEETS["./components.css"];
const motion = SHEETS["./motion.css"];

/** The value a token is declared with in tokens.css. */
function token(name: string): string {
    const found = tokens.match(new RegExp(`${name}:\\s*([^;]+);`));
    expect(found, `${name} is not declared in tokens.css`).not.toBeNull();
    return found![1].trim();
}

/** The declarations inside the first rule with exactly this selector. */
function rule(sheet: string, selector: string): string {
    const at = sheet.indexOf(`${selector} {`);
    expect(at, `no rule for ${selector}`).toBeGreaterThan(-1);
    return sheet.slice(sheet.indexOf("{", at), sheet.indexOf("}", at));
}

describe("the designed motion values", () => {
    it("declares the spec's durations as tokens", () => {
        expect(token("--dur-press")).toBe("90ms");
        expect(token("--dur-quick")).toBe("160ms");
        expect(token("--dur-base")).toBe("260ms");
        expect(token("--dur-loop")).toBe("1600ms");
        expect(token("--dur-boot")).toBe("600ms");
        expect(token("--dur-flash")).toBe("360ms");
        expect(token("--dur-breathe")).toBe("2400ms");
        expect(token("--stagger-led")).toBe("9ms");
        expect(token("--stagger-card")).toBe("50ms");
    });

    it("boots the LEDs over the boot token, nine milliseconds apart", () => {
        const boot = rule(components, ".k-led.boot i.on");
        expect(boot).toContain("var(--dur-boot)");
        expect(boot).toContain("var(--stagger-led)");
    });

    it("rises cards over the base duration, fifty milliseconds apart", () => {
        const enter = rule(motion, ".enter > *");
        expect(enter).toContain("var(--dur-base)");
        expect(enter).toContain("var(--stagger-card)");
    });

    it("breathes the live dot over the breathe token", () => {
        expect(rule(motion, ".live-dot")).toContain("var(--dur-breathe)");
    });

    it("flashes the pipeline's finish over the flash token", () => {
        expect(rule(motion, ".scene-flash")).toContain("var(--dur-flash)");
    });
});
