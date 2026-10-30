# Introduce Kriko to readers who research products

Use the copy below for a directory listing, a community post or a reviewer.
Check the destination rules before submission. Disclose your connection to Kriko.
Do not send the same message to unrelated communities.

## Directory listing

**Name:** Kriko

**Short description:** Check known problems with a product before buying, with a source beside each finding.

**Description:** Kriko is a free, MIT-licensed product research app for Windows.
It shows sourced reports about an exact model and variant.
The browser extension puts findings beside a listing while the desktop app runs.
Installed catalogs support offline lookups without an account or AI key.
Online research uses the agent or provider the reader connects.
Paid providers bill the reader's own account.
No findings means a gap in coverage, not proof that a product has no problems.

**Categories:** Product research, shopping tools, open-source desktop software.

**Links:**

- Website: https://kriko.cc/
- Installation: https://kriko.cc/install/
- Read reports without an app: https://kriko.cc/problems/
- Source and MIT licence: https://github.com/Berbadov/kriko
- Releases: https://github.com/Berbadov/kriko/releases
- Privacy: https://kriko.cc/privacy/

## Community demonstration

**Title:** I built Kriko to put sourced product problems beside a listing

I make Kriko, a free, open-source product research app.
It answers a question I want to ask before buying: what is reported to go wrong with this exact model?

The Windows app and browser extension show findings with links to their sources.
You can confirm the model, read a report and decide what to inspect or ask the seller.
Installed catalogs work offline without an AI key.
Online research needs a connected agent and can have provider costs.

You can browse the reports without an app: https://kriko.cc/problems/
The short guide shows the workflow: https://kriko.cc/guide/
Its demonstration products and findings are invented and labelled as examples.

I would value feedback on the evidence and the first-install experience.
The installer is unsigned. The install page explains verification and the current platform limits.
No findings is not proof that a product is trouble-free.

Source: https://github.com/Berbadov/kriko
Install: https://kriko.cc/install/

## Reviewer introduction

**Subject:** Kriko: sourced product problems beside shopping listings

Hello,

I make Kriko, a free, MIT-licensed product research app for Windows.
It puts known product problems beside a listing, with the source beside each finding.
Installed catalogs work offline. Online research uses the reader's chosen provider.

Readers can try the public reports without an app: https://kriko.cc/problems/
The installation checklist is at https://kriko.cc/install/.
The guide demonstrates a complete check with clearly labelled invented examples.

Would this be useful for a piece about checking a product before buying?
I can provide a demonstration and answer questions about evidence, privacy and coverage limits.

Source and licence: https://github.com/Berbadov/kriko

## Demonstration assets

- Share image, 1200 × 630: https://kriko.cc/assets/share-card.jpg
- Short film: https://kriko.cc/assets/film/kriko-ad.mp4
- Browser workflow: https://kriko.cc/guide/
- Desktop comparison: https://kriko.cc/assets/desktop/compare-light.webp

The film and app screenshots use invented products and findings.
Retain that disclosure wherever an image or film appears.
Do not present an invented example as a review of a real product.

## Suitable destinations

| Destination | Material to prepare | Submission route |
| --- | --- | --- |
| AlternativeTo | Directory description, screenshots and platform limits | https://alternativeto.net/ |
| Show HN | Builder post with a working demo and clear limits | https://news.ycombinator.com/showhn.html |
| r/SideProject | Disclosed builder post and short demonstration | https://www.reddit.com/r/SideProject/ |
| Relevant repair or buying communities | A useful sourced explanation that answers an existing question | Read each community's self-promotion rules first |
| Independent software reviewers | Personal introduction tied to the reviewer's subject | Use the reviewer's published contact route |

These are candidate destinations, not approved placements or endorsements.
Read their current rules. Review or permission may be needed before posting.
No messages or submissions are sent by the website or the build tools.

## Count downloads without a website tracker

GitHub exposes aggregate download counts for published release assets.
Record a baseline outside the repository:

```sh
python site/tools/download-counts.py --save /tmp/kriko-downloads-before.json
```

After distribution, compare the counts:

```sh
python site/tools/download-counts.py --previous /tmp/kriko-downloads-before.json --save /tmp/kriko-downloads-after.json
```

Counts include repeat downloads, automated requests and app updates.
They do not measure unique users, successful installations or which page caused a download.
Use extension-store statistics for extension installs when owner access is available.
The website continues to set no cookies and sends no click events.
