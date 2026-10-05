//! The screens' fixed words: the navigation, the history page size and the
//! compare suggestions. Nothing the engine knows lives here; every number a
//! screen shows comes from `live`.

pub struct NavDef {
    pub key: &'static str,
    pub label: &'static str,
    pub icon: &'static str,
    pub count: Option<&'static str>,
    pub badge: Option<&'static str>,
}

pub struct NavGroupDef {
    pub label: &'static str,
    pub items: &'static [NavDef],
}

pub const NAV: &[NavGroupDef] = &[
    NavGroupDef {
        label: "Check",
        items: &[
            NavDef { key: "home", label: "Home", icon: "home", count: None, badge: None },
            NavDef { key: "run", label: "Run", icon: "run", count: None, badge: None },
            NavDef { key: "history", label: "History", icon: "history", count: None, badge: None },
            NavDef { key: "compare", label: "Compare", icon: "compare", count: None, badge: None },
            NavDef { key: "extension", label: "Browser extension", icon: "extension", count: None, badge: None },
        ],
    },
    NavGroupDef {
        label: "Knowledge",
        items: &[
            NavDef { key: "overview", label: "Overview", icon: "overview", count: None, badge: None },
            NavDef { key: "browse", label: "Browse", icon: "browse", count: Some("760"), badge: None },
        ],
    },
    NavGroupDef {
        label: "System",
        items: &[
            NavDef { key: "sites", label: "Sites", icon: "sites", count: None, badge: None },
            NavDef { key: "activity", label: "Activity", icon: "activity", count: None, badge: Some("1") },
            NavDef { key: "agents", label: "Agents", icon: "agents", count: None, badge: None },
            NavDef { key: "benchmark", label: "Benchmark", icon: "benchmark", count: None, badge: None },
        ],
    },
    NavGroupDef {
        label: "This install",
        items: &[
            NavDef { key: "local", label: "Local LLM", icon: "local", count: None, badge: None },
            NavDef { key: "settings", label: "Settings", icon: "settings", count: None, badge: None },
            NavDef { key: "about", label: "About", icon: "about", count: None, badge: None },
        ],
    },
];

// ---- history: past checks ----

pub const PAGE_SIZE: usize = 5;

// ---- compare ----

/// Suggested follow-up questions, pressed straight from the table. They
/// ask what the board knows, never what to buy.
pub const COMPARE_SUGGESTIONS: &[&str] = &[
    "What does each one's knowledge rest on?",
    "Where do the sources disagree?",
    "What is the single biggest difference between them?",
    "Which claims are settled, and which still open?",
];
