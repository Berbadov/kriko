import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

/**
 * Door 1: the site's own icon in a source row.
 *
 * `docs/DESIGN.md` says the app asks the engine for the site's icon and draws
 * it in the row, and that the reader sees a generated mark when the engine has
 * no icon. The engine's door is `GET /api/favicon` (`src/app/web/routers/
 * favicon.py`): a host in, the image out, a 404 body when there is none, and a
 * thirty-day cache (`src/app/favicon.py`) so a second row for the same host is
 * a file read. Nothing called it.
 *
 * These tests read the window as text, the way the rest of this suite does,
 * and hold the two halves of the contract together: the request's shape
 * against the route that serves it, and the row's mark against the engine's
 * own fallback. The engine half is read, never edited — it is not this
 * suite's to change.
 */

const page = async (path) => readFile(new URL(`../${path}`, import.meta.url), 'utf8')
const engineFile = async (path) => readFile(new URL(`../../${path}`, import.meta.url), 'utf8')
const stripComments = (css) => css.replace(/\/\*[\s\S]*?\*\//g, '')

/** The body of one function in a TSX source, from its declaration to the next. */
function blockOf(source, marker) {
  const at = source.indexOf(marker)
  assert.ok(at > -1, `${marker} was not found`)
  return source.slice(at)
}

test("the window asks the engine's favicon door with a host and nothing else", async () => {
  const client = await page('src/engine/favicons.ts')
  const route = await engineFile('src/app/web/routers/favicon.py')

  // The one request the window makes, in full. A host is the whole input.
  assert.match(client, /`\$\{base\}\/api\/favicon\?host=\$\{encodeURIComponent\(name\)\}`/, 'the icon is not asked for by host')
  assert.doesNotMatch(client, /favicon\?[^`\n]*\b(url|path|size)=/, 'the icon request carries more than a host')

  // The route that serves it takes a host and nothing else, so a caller
  // cannot turn it into a file read or a request to somewhere else.
  const signature = /def icon\((.*?)\) -> Response:/s.exec(route)
  assert.ok(signature, 'the favicon route no longer declares `icon(...)`')
  assert.match(signature[1], /\bhost: str = Query/, 'the route no longer takes a host query')
  assert.doesNotMatch(signature[1], /\b(url|path|size)\b/, 'the route grew an input beyond the host')

  // An image out, or a plain 404 the window treats as "keep the monogram".
  assert.match(route, /Response\(content=body, media_type=kind\)/, 'the route no longer answers with the image bytes')
  assert.match(route, /status_code=404/, 'the route no longer answers a missing icon as a 404')

  // And the engine keeps it for thirty days, so the window asking again for a
  // row re-rendered by a poll is a file read rather than a site fetch.
  const icon = await engineFile('src/app/favicon.py')
  assert.match(icon, /TTL = 30 \* 24 \* 60 \* 60/, 'the icon cache no longer expires in thirty days')
})

test('the icon comes from the engine, which is the only party that may fetch a site', async () => {
  const client = await page('src/engine/favicons.ts')

  // Development: the page and the engine share an origin, and Vite forwards
  // `/api`. The packaged window: its origin is its own, so it uses the engine's
  // fixed listener and only while that listener is this engine's own.
  assert.match(client, /inShell\(\)/, 'the client no longer tells the two windows apart')
  assert.match(client, /get<[^>]*>\('\/api\/extension'/, 'the fixed engine listener is not read from the engine')
  assert.match(client, /port_is_ours/, 'a port that is not this engine\'s could be asked for an icon')
  assert.match(client, /`http:\/\/127\.0\.0\.1:\$\{info\.port\}`/, 'the engine address is not the engine\'s own loopback listener')

  // The window itself never reaches a site: no third-party icon service, and
  // no address built from a host. A row's host only ever becomes a query.
  assert.doesNotMatch(client, /https:\/\/\$\{|favicon\.ico|apple-touch-icon|google\.com|duckduckgo|clearbit/i, 'the window reaches a site or a third party for an icon')
})

test('a source row always carries a mark: the letter under the engine icon', async () => {
  const chip = await page('src/ui/ClaimChip.tsx')
  const mark = blockOf(chip, 'export function SiteMark')
  const body = mark.slice(0, mark.indexOf('\n}\n'))

  // The letter is unconditional and comes first; the image is drawn over it
  // only when the engine has an address to ask.
  const letterAt = body.indexOf('site-mark-letter')
  const imageAt = body.indexOf('<img')
  assert.ok(letterAt > -1, 'the fallback letter is not drawn')
  assert.ok(imageAt > letterAt, 'the image is not drawn over the fallback letter')
  assert.match(body, /\{src && <img/, 'the image is drawn even when there is no engine address')
  assert.match(body, /onError=\{missed\}/, 'a failed image is not reported, so the letter would be hidden by a broken tile')
  assert.doesNotMatch(body, /if \(!src\) return null|!src &&/, 'the mark disappears when there is no icon: that is the empty hole')

  // The letter is the host's, not invented, and a row with no host draws no
  // reserved box at all.
  assert.match(chip, /siteLetter\(host\)/, 'the fallback letter is not derived from the host')
  assert.match(body, /if \(!letter\) return null/, 'a row without a host reserves an empty mark')

  // The box is fixed and the image sits in it, so nothing resizes or spills
  // when the engine's answer arrives.
  const css = stripComments(await page('src/styles/rail.css'))
  assert.match(css, /\.site-mark \{[^}]*position: relative;[^}]*width: 16px;[^}]*height: 16px;[^}]*overflow: hidden;/s, 'the site mark is not a fixed, clipped box')
  assert.match(css, /\.site-mark img \{[^}]*position: absolute;[^}]*inset: 0;[^}]*object-fit: contain;/s, 'the icon is not laid over the letter')
})

test('no icon is asked for twice, and none at all without a live engine', async () => {
  const client = await page('src/engine/favicons.ts')
  const chip = await page('src/ui/ClaimChip.tsx')

  // A host the engine said it has no icon for is remembered for the session:
  // the engine keeps no negative cache, and every row re-rendered by a poll
  // would otherwise be another three site fetches.
  assert.match(client, /const missing = new Set<string>\(\)/, 'there is no memory of hosts with no icon')
  assert.match(client, /missing\.add\(name\)/, 'a failed icon is not remembered')
  assert.match(client, /!failed && !missing\.has\(name\)/, 'a remembered host is asked again')

  // Demo mode and an offline window show the letter and make no request.
  assert.match(client, /if \(mode !== 'live' \|\| !name\) return/, 'the icon is asked for without a live engine')
  assert.match(client, /mode === 'live' && base !== undefined/, 'an address is built while the engine is not live')

  // And the components use the client rather than an <img> of their own.
  assert.match(chip, /useSiteIcon\(host\)/, 'the mark does not go through the engine client')
  assert.doesNotMatch(chip, /favicon\?host/, 'the chip builds the engine address itself')
})

test("both source surfaces draw it: the sources column and the claim chip", async () => {
  const rail = await page('src/ui/ChatRail.tsx')
  const chip = await page('src/ui/ClaimChip.tsx')

  // The sources column: a page row leads with its site's mark, derived from
  // the engine's host or the page address it gave.
  assert.match(rail, /import \{ siteHost \} from '\.\.\/engine\/favicons'/, 'the rail does not read the host from the engine\'s own value')
  assert.match(rail, /import \{ SiteMark \} from '\.\/ClaimChip'/, 'the rail does not draw the shared site mark')
  assert.match(rail, /const host = siteHost\(page\.host, page\.url\)/, 'the rail derives the mark from something other than the page')
  assert.match(rail, /\{host && <SiteMark host=\{host\} \/>\}/, 'a source row does not draw the site mark')

  // The claim chip: a source behind a finding carries the same mark.
  assert.match(chip, /const mark = siteHost\(source\.host, source\.url\)/, 'the chip derives the mark from something other than the source')
  assert.match(chip, /\{mark && <SiteMark host=\{mark\} \/>\}/, 'a claim source chip does not draw the site mark')
})
