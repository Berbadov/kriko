# Shared access: one password, inside this app only — 2026-10-23

The owner's words: *"i give them a password they paste it into settings and then
they can use kriko agent easily on my api keys. which are secure right now. so
password should not work outside of kriko app."* And, for people nobody has
vetted: *"a few query allowance for the first timer unknown people that want to
test the app. still using my keys but its limited on kriko agent."*

The code is `src/app/sharekeys.py`; the door is `/api/keys/shared/*` in
`src/app/web/routers/keys.py`; the screen is **Settings → Shared access**.

## What travels, and what does not

| Thing | Where it lives | Who can use it |
|---|---|---|
| Mercury and DeepSeek keys | The owner's computer, and inside the sealed code | Kriko Agent, on the owner's machine or a friend's |
| The **access code** | One line the owner sends | Anyone who also has the password **and** this app |
| The **password** | In the owner's head, sent separately from the code | Nothing on its own |
| The **pepper** | Inside the shipped build; not in this repository | Whoever holds the app |
| The **device key** | `~/.kriko/device.key`, DPAPI-protected on Windows | This Windows account, on this computer |

The password is never stored, in any form, by either side. Neither is a key
written in the clear: what the friend's computer keeps is the opened grant,
sealed again under its own device key.

## The protocol

Two directions, both in `src/app/sharekeys.py`.

**Owner → code.** The owner types a password in Settings and presses *Make an
access code*.

1. `salt = 16 random bytes`; `key = scrypt(password ‖ pepper, salt, n=2¹⁵, r=8, p=1, dklen=32)`.
   The pepper is mixed into the passphrase, so a code sealed by a build that has
   one does not open in a build that does not — in either direction.
2. The payload is `{"mercury": …, "deepseek": …}` as compact sorted JSON, sealed
   with AES-256-GCM under `key`, with the associated data
   `kriko/shared-access/grant/v1`.
3. The code is `base64url("KSA1" ‖ salt) + "." + base64url(nonce ‖ ciphertext)`.

**Code → friend.** The friend pastes the code and the password.

1. The salt comes out of the first half, `key` is derived the same way, and the
   second half is opened with the same associated data. A wrong password, a
   damaged code and a code from another build are one answer: *"the password is
   not the one this code was made with, or the code was changed on the way."*
2. The opened keys are sealed under the device key and written to
   `~/.kriko/shared.json`. On Windows that key is DPAPI-protected
   (`CryptProtectData`), so a copy of `~/.kriko` on another machine opens
   nothing; on macOS and Linux the device key is a 0600 file and the same copy
   does open — `GET /api/keys/shared/status` says which one is in use
   (`"device": "dpapi" | "file"`).
3. `keys.require()` finds them last: `os.environ`, then `~/.kriko/env`, then the
   shared grant, then the trial. A key of the reader's own always wins.

## The trial

A build can carry a bundle that needs no password at all, because there is
nobody to give one to:

    python tools/make_share_pepper.py          # once per build (gitignored)
    python tools/make_trial_access.py          # bake the trial bundle (gitignored)

The bundle is the same payload sealed under a key derived from the pepper alone
(`kriko/shared-access/trial/v1`), so anyone who installs the app can open it and
nobody without the app can. It is written to `src/app/trial_access.json` — JSON
because the frozen sidecar bundles every `src/app/*.json` and a bundle that is
not there is simply absent. `TRIAL_QUESTIONS` (10 by default, settable with
`--questions`) is counted in `shared.json` on the reader's own machine, and one
Kriko Agent question costs one, counted before the model is asked.

**The count is a courtesy, not a wall.** A reader who deletes their own
`shared.json` starts again, and the bundle is in the download. What actually
bounds the loss is the owner's own doing, and the order matters:

1. Make a **separate** key pair for the trial. Do not bake the personal keys.
2. Set a spend limit on those keys at the provider.
3. Bake, publish, and **rotate the pair** with the next release.
4. Watch the provider's usage page; if it moves faster than the trial count
   suggests, rotate immediately.

## What this does and does not hold

Holds:

- The password alone is nothing: no key, no code, no access.
- Code and password together are nothing without this app: the derivation needs
  the pepper, which is in the binary and not in the repository.
- Nothing writes a key in the clear: not `env`, not `shared.json`, not any
  response body (the endpoint rule in `routers/keys.py` still stands, and
  `test_the_endpoints_never_return_a_key` searches every reply for one).
- A grant copied to another computer does not open, on Windows.
- `GET /api/keys/shared/status` never returns a key, a password or a code.

Does not hold, and cannot:

- **A friend who has been given access can recover the keys on their own
  machine.** They must be usable there for Kriko Agent to work; anything the app
  can decrypt, its owner can decrypt. Treat a shared code as "a friend can spend
  my keys", because that is what it is.
- **The app's own local API is not authenticated.** A program running as the
  same user could ask this engine to spend a shared key (and could read
  `~/.kriko` directly). Closing that means a token minted by the sidecar and
  carried by the desktop shell's `engine_request`, which is a change to the
  shell contract rather than to this protocol; it is not in 0.3.1.
- **Revocation is the owner rotating the keys** at Inception and DeepSeek.
  Nothing here can reach into a friend's computer and take a code back. The
  password is per-code, so a leak is one code, not all of them.
- A code made by a build **without** a pepper opens in any build. The screen
  says so when `status()["bound"]` is false, and the tools refuse to bake a
  trial without one.

## Operating it

Owner:

1. Settings → Research: the Mercury and DeepSeek keys are saved on this computer.
2. Settings → Shared access → *Sharing your own keys with a friend*: type a
   password of at least 8 characters, press *Make an access code*, copy the code.
3. Send the code and the password in **two separate messages**. Anyone with both
   can use the keys in their Kriko.
4. To stop a code working, replace the Mercury and DeepSeek keys at the
   providers. Every code made from the old pair stops working with them.

Friend:

1. Install Kriko (the same installer the owner uses).
2. Settings → Shared access: paste the code, paste the password, press *Use
   these keys*.
3. Ask Kriko Agent a question. Nothing else in the app changes: their own keys
   and settings are untouched, and *Forget them* removes the grant.

Nothing about this needs a server, an account or a network round trip beyond the
provider calls themselves.
