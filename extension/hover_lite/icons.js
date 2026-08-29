/* Inline icon set — 24×24 viewBox, stroke-based, currentColor. No CDN. */

(function () {
  const ICON_PATHS = {
    chevronDown:  '<path d="M6 9l6 6 6-6" />',
    plus:         '<path d="M12 5v14" /><path d="M5 12h14" />',
    minus:        '<path d="M5 12h14" />',
    x:            '<path d="M18 6 6 18" /><path d="M6 6l12 12" />',
    refresh:      '<path d="M3 12a9 9 0 0 1 15-6.7L21 8" /><path d="M21 3v5h-5" /><path d="M21 12a9 9 0 0 1-15 6.7L3 16" /><path d="M3 21v-5h5" />',
    scan:         '<path d="M3 7V5a2 2 0 0 1 2-2h2" /><path d="M17 3h2a2 2 0 0 1 2 2v2" /><path d="M21 17v2a2 2 0 0 1-2 2h-2" /><path d="M7 21H5a2 2 0 0 1-2-2v-2" /><path d="M7 12h10" />',
    search:       '<circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" />',
    rowsLoose:    '<path d="M3 5h18" /><path d="M3 12h18" /><path d="M3 19h18" />',
    rowsCompact:  '<path d="M3 6h18" /><path d="M3 12h18" /><path d="M3 18h18" />',
    panelRight:   '<rect x="3" y="3" width="18" height="18" rx="2" /><path d="M15 3v18" />',
    info:         '<circle cx="12" cy="12" r="9" /><path d="M12 8h.01" /><path d="M11 12h1v5h1" />',
    alert:        '<circle cx="12" cy="12" r="9" /><path d="M12 7v6" /><path d="M12 17h.01" />',
    eye:          '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z" /><circle cx="12" cy="12" r="3" />',
    shield:       '<path d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6l-8-3Z" />',
    engine:       '<circle cx="12" cy="12" r="3" /><path d="M12 2v3" /><path d="M12 19v3" /><path d="M2 12h3" /><path d="M19 12h3" /><path d="M4.9 4.9l2.1 2.1" /><path d="M17 17l2.1 2.1" /><path d="M4.9 19.1 7 17" /><path d="M17 7l2.1-2.1" />',
    fuel:         '<path d="M3 22V5a2 2 0 0 1 2-2h6a2 2 0 0 1 2 2v17" /><path d="M3 14h10" /><path d="M14 8h2a2 2 0 0 1 2 2v7a2 2 0 0 0 2 2 2 2 0 0 0 2-2V9.5L18 5" />',
    car:          '<path d="M14 16H9m10 0h2v-3.5a2 2 0 0 0-.6-1.4l-1.6-1.6a2 2 0 0 0-1.4-.6h-1l-2.4-3.2A2 2 0 0 0 12.4 5H7.4a2 2 0 0 0-1.7 1L4 9.4H3a2 2 0 0 0-2 2V16h2" /><circle cx="7" cy="17" r="2" /><circle cx="17" cy="17" r="2" />',
    transmission: '<circle cx="6" cy="6" r="3" /><circle cx="18" cy="6" r="3" /><circle cx="6" cy="18" r="3" /><path d="M6 9v6" /><path d="M9 6h6a3 3 0 0 1 3 3" />',
    wind:         '<path d="M3 8h12a3 3 0 1 0-3-3" /><path d="M3 16h17a3 3 0 1 1-3 3" /><path d="M3 12h11" />',
    factory:      '<path d="M3 21V8l6 4V8l6 4V3h6v18Z" /><path d="M7 17h2" /><path d="M13 17h2" /><path d="M19 17h-2" />',
    wrench:       '<path d="M15 4a5 5 0 0 0-5 5v1L3 17l3 3 7-7h1a5 5 0 0 0 4.6-7.1L16 9l-2-2 1.4-3.4Z" />',
    bodyStructure:'<path d="M4 17V8l4-3h8l4 3v9" /><path d="M4 17h16" /><circle cx="8" cy="17" r="1.5" /><circle cx="16" cy="17" r="1.5" /><path d="M9 12h6" />',
  };

  // Lowercase keys only — domainIconSvg lowercases before lookup. Covers both
  // the design-system grammar ("fuel system", "body/structure") and the
  // Title-case domains the backend emits ("Engine", "Cooling", "Suspension"…).
  const DOMAIN_ICON = {
    "engine":         "engine",
    "transmission":   "transmission",
    "fuel system":    "fuel",
    "fuel":           "fuel",
    "body/structure": "bodyStructure",
    "body":           "bodyStructure",
    "interior":       "bodyStructure",
    "emissions":      "wind",
    "exhaust":        "wind",
    "cooling":        "engine",
    "turbocharger":   "engine",
    "turbo":          "engine",
    "manufacturing":  "factory",
    "electrical":     "engine",
    "electronics":    "engine",
    "suspension":     "car",
    "brakes":         "car",
    "steering":       "transmission",
    "general":        "wrench",
  };

  function iconSvg(name, { size = 16, strokeWidth = 1.75 } = {}) {
    const inner = ICON_PATHS[name];
    if (!inner) return "";
    return (
      '<svg width="' + size + '" height="' + size + '" viewBox="0 0 24 24" ' +
      'fill="none" stroke="currentColor" stroke-width="' + strokeWidth + '" ' +
      'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" ' +
      'style="display:inline-block;flex:0 0 auto;">' + inner + '</svg>'
    );
  }

  function domainIconSvg(domain, opts = {}) {
    const key = domain ? String(domain).toLowerCase().trim() : "";
    const name = DOMAIN_ICON[key] || "wrench";
    return iconSvg(name, opts);
  }

  window.__KrikoPanelIcons = { ICON_PATHS, DOMAIN_ICON, iconSvg, domainIconSvg };
})();
