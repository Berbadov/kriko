# Kriko relay

A small server you run yourself (a $5 a month machine is enough), **for one reader**:
you. It does two jobs:

1. **Sync.** Your phone and your computer keep the same profile, purchases and
   watches. The relay stores them as ciphertext sealed on your devices with a key
   it never receives.
2. **Watch while the computer is off.** For the pages you choose, the relay reads
   the page a few times a day and pushes an alert to your phone through
   [ntfy](https://ntfy.sh) when the price crosses what you asked for.

## What the relay can and cannot see

| It stores | Readable by the relay? |
|---|---|
| Profile, purchases, watch settings (blobs) | No. AES-256-GCM, key held by your devices only |
| You | The hash of a token derived from your key. No account, email or name. The first device to present the setup word claims the relay; nobody else can |
| A page you turned on in the cloud | **Yes, the address.** A server that fetches a page has to know it. Hashing cannot change that. It is kept encrypted at rest under `KRIKO_CLOUD_SECRET`, and addressed everywhere else (the API, logs) by its hash |
| What that product is called | Only if you let it. With private labels the relay is told "a page you watch", never the name |
| A push | A label and a price, sent to your ntfy topic. Never an address |

Pages you do not turn on in the cloud are never sent.

If you would rather the relay never learn a page, do not turn that watch on in the
cloud: the desktop still watches it whenever it is running.

## Run it

```bash
cd server
cp .env.example .env        # set KRIKO_CLOUD_SECRET and KRIKO_CLOUD_SETUP (openssl rand -hex 32) and your domain
docker compose up -d --build
```

`docker-compose.yml` runs the relay behind Caddy, which gets a certificate for your
domain. Open ports 80 and 443 and point a DNS name at the machine.

In Kriko, open **More, For you, Phone and relay**, enter `https://your.domain` and
the setup word from your `.env`, and press Connect. Do it soon after starting the
relay: until the first device claims it, the setup word is all that stands between a
stranger and your relay, and a relay with no setup word refuses every claim. Press
**Pair a phone** to show the pairing code. The setup word is needed only once.

To start over, press Disconnect in Kriko (it releases the relay), or delete the
`relay-data` volume.

Alerts to a phone: install the ntfy app and subscribe to the topic Kriko shows
beside the code. By default alerts go through the public ntfy.sh, which can see the
label and price in the push. To keep them to yourself, run your own ntfy (see its
documentation) and set `KRIKO_CLOUD_NTFY` to its address.

## Keep it safe

- **Fetching other people's addresses is the risky part.** The relay refuses
  anything that does not resolve to a public address (checked again at every
  redirect), only ordinary ports, only text pages, 2 MB at most. Run it in a
  container that has no route to your own network as a second wall.
- Set `KRIKO_CLOUD_SECRET`. Without it a key is made beside the database, which
  protects nothing from someone who copies the disk.
- Back up the `relay-data` volume. Losing it loses nothing of yours: the devices
  hold everything, and a reconnect re-sends it. Losing `KRIKO_CLOUD_SECRET` only
  loses the watched addresses, which the desktop re-sends on its next sync.
- Limits are environment variables (`KRIKO_CLOUD_MAX_WATCHES`, `KRIKO_CLOUD_MAX_BLOB`).
  One relay serves one reader, so there is no account system to defend: whoever holds
  the key owns it, and a lost phone means pressing Disconnect and connecting again.

## The protocol, for a phone app

Everything is derived from one 32-byte key (HKDF-SHA256, info `kriko/<name>`):
`token` (32 bytes, base64url, the bearer token), `topic` (`kriko-` plus 16 bytes, hex)
and `enc` (the AES-256-GCM key). A blob is
`b"K1" + nonce(12) + ciphertext`, with the blob's name as associated data. See
`src/app/cloud.py`; the routes are in `server/kriko_cloud/app.py`.

| Route | |
|---|---|
| `PUT /v1/owner` | claim the relay (first time: header `X-Kriko-Setup`), or confirm it; body `{"topic": ...}` |
| `GET/PUT /v1/blob/{name}` | a sealed blob; `X-Kriko-Expect: <version>` on a write; 409 if it moved |
| `GET /v1/watches`, `PUT/DELETE /v1/watch/{id}` | cloud watches |
| `GET /v1/alerts?after=<id>` | alerts raised while the devices were off |
| `DELETE /v1/owner` | forget everything and free the relay |

## Develop

```bash
PYTHONPATH=server python -m kriko_cloud       # http://127.0.0.1:8080
pytest server/tests
```
