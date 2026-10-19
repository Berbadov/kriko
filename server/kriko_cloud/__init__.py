"""Kriko's relay: sync a reader's phone and computer, and watch prices while the computer is off.

A small server that a reader can run on a few dollars a month. It is built around
one rule, stated here so every file can be checked against it: **the server learns
as little as the job needs and nothing more.**

* What the reader keeps (profile, ledger, watches) arrives as ciphertext sealed on
  their device with a key the server never receives. The server stores bytes.
* A group has no account, no email and no name. It is a random id and the hash of a
  secret that both devices derive from a key they were paired with.
* The one exception is a **cloud watch**. A server that re-reads a page has to be
  told the page, and hashing the address cannot change that: whoever fetches a page
  knows where it is. So a watch is sent only when the reader turns that watch on in
  the cloud, and the address is kept encrypted at rest under the operator's key and
  addressed everywhere else (logs, indexes, shared fetches) by its hash.
* The same page watched by many groups is fetched once, which is also what keeps
  the shops' load, and the server's bill, small.
* Alerts go out as a push (ntfy) to a topic only the paired devices can derive.
"""

__version__ = "0.1.0"
