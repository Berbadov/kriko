import type { AnchorHTMLAttributes, MouseEvent } from 'react'
import { inShell } from '../engine/api'

/** Open a web address in the reader's own browser.
 *  The packaged window ignores `target="_blank"`, so a link did nothing there. The shell
 *  opens the address; only http and https go, because an answer is remote text. */
export async function openLink(href: string): Promise<void> {
  let url: URL
  try {
    url = new URL(href, window.location.href)
  } catch {
    return
  }
  if (url.protocol !== 'https:' && url.protocol !== 'http:') return
  if (!inShell()) {
    window.open(url.href, '_blank', 'noopener,noreferrer')
    return
  }
  const { invoke } = await import('@tauri-apps/api/core')
  await invoke('plugin:opener|open_url', { url: url.href }).catch(() => undefined)
}

export function ExternalLink({ href, children, ...rest }: AnchorHTMLAttributes<HTMLAnchorElement>) {
  const open = (event: MouseEvent<HTMLAnchorElement>) => {
    if (!href || event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return
    event.preventDefault()
    void openLink(href)
  }
  return (
    <a {...rest} href={href} target="_blank" rel="noopener noreferrer" onClick={open}>
      {children}
    </a>
  )
}
