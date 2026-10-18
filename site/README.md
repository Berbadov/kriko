# Kriko website

The public landing page is static HTML, CSS and JavaScript. There is no build
step and no client-side framework. Serve the entire `site/` directory so its
stylesheet, script and assets are included.

From the repository root:

```sh
npm run serve:site
```

Open `http://127.0.0.1:4173`. Alternatively, open `site/index.html` directly.
Google Fonts is optional; system fonts are the fallback.

The interactive walkthrough includes a Golf 7 finding from the Cars catalog,
plus MacBook Air M2, Sony WH-1000XM5 and Breville Barista Express examples.
Product buttons update the hero illustration, listing, checks and source links
together. The product cards also select an example and open its walkthrough.
Without JavaScript, the additional product cards open the original sources.
The page presents investigative research for both new and used purchases.
Its default laptop example follows a teardown detail into a question about
configuration-specific tests. The headphones example connects owner hinge
reports with repair information. The espresso example compares conflicting
noise reports without assigning a cause. Each example distinguishes evidence,
an unresolved question and the next research step.
These are static research examples. They do not claim that these categories
have published catalogs or that a live research run occurred.
The car example shows an inspection of a used vehicle. The two purchase paths
open these examples without filtering the app to either buying situation.
All listings are illustrative. The preview does not query the desktop
app, send product data, run research, or require an account. Source links open
the original pages. Download links use GitHub's latest release page so their
labels do not get stuck on a particular version.

Motion includes entrance transitions, scroll reveals, a floating finding,
an orbital illustration, button feedback and an optional timed walkthrough.
The page respects reduced-motion preferences, includes a pause control, and
pauses the hero animation outside the viewport. The walkthrough runs once
when requested, pauses in background tabs and stops when it leaves the screen.
Tabs support arrow keys, Home and End. With JavaScript disabled, all three
walkthrough panels appear in order.

Run the interaction checks after installing the root development dependencies:

```sh
npm ci
npm run test:site
```

These checks use jsdom, not a rendering browser. Check the layout in a browser
at phone, tablet and desktop widths before publishing. Publish the contents
of `site/` with the existing hosting process.
