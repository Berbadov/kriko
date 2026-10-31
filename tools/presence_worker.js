// The counting side of Kriko's optional anonymous presence ping
// (`src/app/presence.py`). Deploy as a Cloudflare Worker (free tier is plenty):
//
//   wrangler deploy server/presence_worker.js
//
// The app POSTs {"id": <32 hex chars>, "version": "0.3.7"} once a day, only
// from installs that opted in. The Worker stores one row per (id, day) in a
// KV namespace; counting distinct ids over the last 30 days is the MAU number.
// It stores nothing else, and the id is random per install, so the store
// holds no personal data. `wrangler kv namespace create PRESENCE`.

export default {
  async fetch(request, env) {
    if (request.method !== 'POST' || new URL(request.url).pathname !== '/ping') {
      return new Response('not found', { status: 404 })
    }
    let body
    try {
      body = await request.json()
    } catch {
      return new Response('bad request', { status: 400 })
    }
    const id = typeof body.id === 'string' ? body.id : ''
    const version = typeof body.version === 'string' ? body.version.slice(0, 40) : ''
    if (!/^[0-9a-f]{32}$/.test(id) || !version) {
      return new Response('bad request', { status: 400 })
    }
    const day = new Date().toISOString().slice(0, 10)
    await env.PRESENCE.put(`${day}:${id}`, version, { expirationTtl: 60 * 60 * 24 * 45 })
    return new Response('ok', { status: 200 })
  },
}
