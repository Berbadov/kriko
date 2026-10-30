# Installation and product-page previews

These are Chromium screenshots of the static website at desktop and phone widths.
The pages were also checked without JavaScript.

- [English installation on a phone](install-en-mobile.png)
- [Turkish installation on a phone](install-tr-mobile.png)
- [Generated product page on desktop](product-en-desktop.png)
- [Generated Turkish product page on a phone](product-tr-mobile.png)

The browser check opens the verification instructions and mobile menu.
It checks for horizontal overflow and localized installation links.

To capture them again, start `npm run serve:site`, then run:

```sh
SCREENSHOTS=docs/previews/2026-10-30-acquisition npm run test:site:browser
```

Set `PLAYWRIGHT_MODULE` and `CHROMIUM_PATH` if Playwright and Chromium are installed outside the project.
