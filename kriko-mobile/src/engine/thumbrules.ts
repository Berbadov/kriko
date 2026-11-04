/**
 * The rule behind the folder of chat pictures, kept free of any native module
 * so it can be checked without a phone.
 */

/**
 * Which stored pictures nothing refers to any more. A picture is kept only
 * while a chat or a scan record points at it by address inside `folder`.
 */
export function orphanedThumbnails(
  names: readonly string[],
  referenced: Iterable<string | undefined>,
  folder: string,
): string[] {
  const kept = new Set<string>();
  for (const uri of referenced) {
    if (uri && uri.startsWith(folder)) kept.add(uri.slice(folder.length));
  }
  return names.filter((name) => !kept.has(name));
}
