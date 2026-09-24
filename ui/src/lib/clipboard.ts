/** Put text on the clipboard; `true` when it got there.
 *
 * Five buttons each wrapped `navigator.clipboard.writeText` in a try whose
 * catch did nothing, so where the async clipboard is refused — a webview
 * without the permission, a browser that wants a user gesture it did not
 * count — pressing Copy changed nothing on screen and nothing reached the
 * clipboard. `execCommand("copy")` is deprecated and still the one path
 * those contexts allow; and when both fail the caller is told, so the button
 * can say so instead of looking broken.
 */
export async function copyText(text: string): Promise<boolean> {
    try {
        await navigator.clipboard.writeText(text);
        return true;
    } catch {
        /* fall through to the older path */
    }
    try {
        const area = document.createElement("textarea");
        area.value = text;
        area.setAttribute("readonly", "");
        area.style.position = "fixed";
        area.style.opacity = "0";
        document.body.appendChild(area);
        area.select();
        const ok = document.execCommand("copy");
        area.remove();
        return ok;
    } catch {
        return false;
    }
}

/** What a copy button says after it was pressed. */
export const copyWord = (ok: boolean) => (ok ? "Copied" : "Clipboard blocked — select the text instead");
