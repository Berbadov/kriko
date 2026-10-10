# Firefox add-on

Kriko uses one extension source for Chromium and Firefox. The Firefox build
replaces the service worker with a background event page, adds a stable Gecko
ID, declares its page-data use, and removes Chromium's dynamic resource URL
option. The native Extension screen stages each browser in a separate folder.

Firefox 140 or newer is required for built-in data collection consent. The
add-on sends page URLs, product names, codes, labelled facts and seller text
to the Kriko desktop engine, normally at `http://127.0.0.1:8787`. This counts
as transmission outside the browser even though the destination is local.
The manifest declares browsing activity and website content accordingly.
There is no analytics service in the add-on. Kriko's research provider is the
one the reader configures; a hosted provider may receive research inputs.
The optional API-base override in extension options changes the destination.

The default site permissions come from the shared manifest. Other HTTPS sites
require the reader to grant access. Installing a catalog does not grant browser
permissions. Firefox's private session storage is bridged to the matching tab
with messages; live results and progress are not persisted to local storage
as a workaround.

Build an unsigned package from a development environment:

```powershell
python packaging/build_extension.py --output reports/kriko-firefox-unsigned.xpi
```

For a preview, use **Load Temporary Add-on** on
`about:debugging#/runtime/this-firefox` and select that XPI, or prepare it in
the native app and select its `manifest.json`. Firefox removes temporary
add-ons on restart. This preview is not a permanent installation.

For permanent distribution, upload the generated XPI to Mozilla's developer
hub for signing under **On your own** (unlisted distribution), or publish an
AMO listing. Keep the Gecko ID `kriko@kriko.local` consistent for updates.
Signing needs the developer's Mozilla account. No upload or publication is
performed by the build command. The unsigned XPI cannot be installed as a
normal add-on in Firefox Release or Beta.

Mozilla documentation: [background scripts](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/manifest.json/background),
[data consent](https://extensionworkshop.com/documentation/develop/firefox-builtin-data-consent/),
[temporary installation](https://extensionworkshop.com/documentation/develop/temporary-installation-in-firefox/),
[signing and distribution](https://extensionworkshop.com/documentation/publish/signing-and-distribution-overview/).
