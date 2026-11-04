/**
 * One plain line from an answer written in Markdown, for a list row that has
 * room for a single line: no heading marks, bullets, emphasis, links or
 * citation numbers, and no line breaks.
 */
export function plainPreview(markdown: string): string {
  return markdown
    .replace(/```[a-z]*/gi, ' ')
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/\[\d+(?:\s*,\s*\d+)*\]/g, '')
    .replace(/^[ \t]*#{1,6}[ \t]+/gm, '')
    .replace(/^[ \t]*(?:[-*+•]|\d+[.)])[ \t]+/gm, '')
    .replace(/(\*\*|__|\*|_|`)/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}
