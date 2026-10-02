//! Sample data for the Kriko screens. Pack and subject names stand in for the
//! local store; claims and numbers are placeholders, exactly as the footer
//! note under each screen says.

use crate::theme::{TagState, Verdict};

pub const FOOTER_NOTE: &str =
    "Sample data. Pack and subject names come from the local store; claims and numbers are placeholders.";

// ---- navigation ----

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

pub struct Check {
    pub name: &'static str,
    pub pack: &'static str,
    pub verdict: Verdict,
    pub confidence: u8,
    pub agents: &'static [char],
    pub took: &'static str,
    pub when: &'static str,
}

pub const CHECKS: &[Check] = &[
    Check { name: "Samsung Galaxy Buds2 Pro", pack: "samsung.headphones", verdict: Verdict::Recommended, confidence: 82, agents: &['C', 'O'], took: "3 min 12", when: "2 min ago" },
    Check { name: "Samsung Galaxy Buds Pro", pack: "samsung.headphones", verdict: Verdict::WeighUp, confidence: 61, agents: &['C', 'G'], took: "5 min 40", when: "Yesterday" },
    Check { name: "Samsung Galaxy Buds Live", pack: "samsung.headphones", verdict: Verdict::Avoid, confidence: 74, agents: &['O'], took: "2 min 05", when: "3 days ago" },
    Check { name: "Apple iPhone 15", pack: "apple.iphone15", verdict: Verdict::Recommended, confidence: 79, agents: &['C', 'C'], took: "4 min 51", when: "Last week" },
    Check { name: "Volkswagen Passat 2020", pack: "volkswagen.passat.2020", verdict: Verdict::WeighUp, confidence: 58, agents: &['M'], took: "9 min 30", when: "Last week" },
    Check { name: "Sony WH-1000XM5", pack: "sony.headphones", verdict: Verdict::Recommended, confidence: 88, agents: &['C', 'O'], took: "2 min 48", when: "Last week" },
    Check { name: "Toyota Corolla 2021", pack: "toyota.cars", verdict: Verdict::WeighUp, confidence: 64, agents: &['M'], took: "8 min 02", when: "2 weeks ago" },
    Check { name: "Apple AirPods Pro 2", pack: "apple.headphones", verdict: Verdict::Recommended, confidence: 85, agents: &['C', 'C'], took: "3 min 55", when: "2 weeks ago" },
    Check { name: "Bose QuietComfort Ultra", pack: "bose.headphones", verdict: Verdict::WeighUp, confidence: 69, agents: &['G'], took: "6 min 12", when: "3 weeks ago" },
    Check { name: "Ford Focus 2019", pack: "ford.cars", verdict: Verdict::Avoid, confidence: 71, agents: &['M'], took: "7 min 44", when: "3 weeks ago" },
    Check { name: "JBL Tour Pro 2", pack: "jbl.headphones", verdict: Verdict::Recommended, confidence: 76, agents: &['O'], took: "4 min 09", when: "Last month" },
    Check { name: "Hyundai Ioniq 5", pack: "hyundai.cars", verdict: Verdict::WeighUp, confidence: 66, agents: &['M', 'C'], took: "10 min 18", when: "Last month" },
    Check { name: "Anker Soundcore Liberty 4", pack: "anker.headphones", verdict: Verdict::Recommended, confidence: 73, agents: &['O'], took: "5 min 27", when: "Last month" },
    Check { name: "Honda Civic 2022", pack: "honda.cars", verdict: Verdict::WeighUp, confidence: 62, agents: &['M'], took: "9 min 03", when: "Last month" },
    Check { name: "Sennheiser Momentum 4", pack: "sennheiser.headphones", verdict: Verdict::Recommended, confidence: 81, agents: &['G'], took: "3 min 41", when: "2 months ago" },
    Check { name: "BMW 3 Series 2021", pack: "bmw.cars", verdict: Verdict::WeighUp, confidence: 59, agents: &['M', 'O'], took: "11 min 06", when: "2 months ago" },
    Check { name: "Nothing Ear 2", pack: "nothing.headphones", verdict: Verdict::Avoid, confidence: 77, agents: &['O'], took: "2 min 33", when: "2 months ago" },
    Check { name: "Kia EV6 2023", pack: "kia.cars", verdict: Verdict::Recommended, confidence: 84, agents: &['C'], took: "8 min 51", when: "2 months ago" },
    Check { name: "Beats Studio Pro", pack: "beats.headphones", verdict: Verdict::WeighUp, confidence: 67, agents: &['G', 'O'], took: "4 min 44", when: "3 months ago" },
    Check { name: "Volkswagen Golf 2020", pack: "volkswagen.cars", verdict: Verdict::WeighUp, confidence: 63, agents: &['M'], took: "7 min 19", when: "3 months ago" },
    Check { name: "Technics EAH-AZ80", pack: "technics.headphones", verdict: Verdict::Recommended, confidence: 80, agents: &['C', 'O'], took: "5 min 58", when: "3 months ago" },
    Check { name: "Mazda 3 2021", pack: "mazda.cars", verdict: Verdict::Avoid, confidence: 72, agents: &['M'], took: "6 min 37", when: "4 months ago" },
    Check { name: "Audio-Technica M50x", pack: "audiotechnica.headphones", verdict: Verdict::Recommended, confidence: 78, agents: &['O'], took: "3 min 22", when: "4 months ago" },
    Check { name: "Renault Zoe 2022", pack: "renault.cars", verdict: Verdict::WeighUp, confidence: 57, agents: &['M', 'G'], took: "9 min 45", when: "4 months ago" },
    Check { name: "Shure Aonic 215", pack: "shure.headphones", verdict: Verdict::WeighUp, confidence: 60, agents: &['G'], took: "4 min 16", when: "5 months ago" },
    Check { name: "Polestar 2 2023", pack: "polestar.cars", verdict: Verdict::Recommended, confidence: 83, agents: &['C', 'M'], took: "10 min 40", when: "5 months ago" },
];

pub const PAGE_SIZE: usize = 5;

// ---- activity feed ----

pub struct FeedEntry {
    pub time: &'static str,
    pub text: &'static str,
    pub kind: &'static str,
    pub state: TagState,
}

pub const FEED: &[FeedEntry] = &[
    FeedEntry { time: "now", text: "Antigravity CLI needs you to sign in", kind: "agents", state: TagState::Block },
    FeedEntry { time: "2 min", text: "Run 14 stored 12 new claims", kind: "run", state: TagState::Queue },
    FeedEntry { time: "9 min", text: "forum.test blocked a page, skipped", kind: "sites", state: TagState::Queue },
    FeedEntry { time: "21 min", text: "Pack samsung.headphones enabled", kind: "knowledge", state: TagState::Queue },
    FeedEntry { time: "1 h", text: "Check finished: Buds2 Pro, recommended", kind: "history", state: TagState::Queue },
    FeedEntry { time: "2 h", text: "Claim settled: Buds2 Pro battery is 5 h", kind: "knowledge", state: TagState::Done },
    FeedEntry { time: "4 h", text: "Agent opencode connected, 58 ms", kind: "agents", state: TagState::Live },
    FeedEntry { time: "6 h", text: "Run 13 stored 9 new claims", kind: "run", state: TagState::Queue },
];

// ---- agents ----

pub struct AgentInfo {
    pub name: &'static str,
    pub kind: &'static str,
    pub monogram: char,
    pub state: TagState,
    pub state_label: &'static str,
    pub latency: &'static str,
    pub allowed: bool,
    pub detail: &'static str,
    pub last_seen: &'static str,
    pub runs: u16,
    /// The MCP port this agent talks to Kriko on.
    pub port: &'static str,
    /// Which tools the agent may use: read pages, take part in Run, answer questions.
    pub can_read: bool,
    pub can_run: bool,
    pub can_answer: bool,
}

pub const AGENTS: &[AgentInfo] = &[
    AgentInfo { name: "Claude Code", kind: "CLI", monogram: 'C', state: TagState::Live, state_label: "Connected", latency: "42 ms", allowed: true, detail: "Runs from PATH; reads the MCP server on localhost.", last_seen: "2 min ago", runs: 34, port: "7401", can_read: true, can_run: true, can_answer: true },
    AgentInfo { name: "opencode", kind: "CLI", monogram: 'O', state: TagState::Live, state_label: "Connected", latency: "58 ms", allowed: true, detail: "Runs from PATH; reads the MCP server on localhost.", last_seen: "9 min ago", runs: 21, port: "7401", can_read: true, can_run: true, can_answer: true },
    AgentInfo { name: "Antigravity CLI", kind: "CLI", monogram: 'A', state: TagState::Need, state_label: "Needs you", latency: "sign in", allowed: false, detail: "Found on PATH but not signed in. It will be skipped in Run until you sign in.", last_seen: "1 h ago", runs: 0, port: "7401", can_read: false, can_run: false, can_answer: false },
    AgentInfo { name: "Mistral Vibe", kind: "CLI", monogram: 'M', state: TagState::Queue, state_label: "Not found", latency: "n/a", allowed: false, detail: "Not found on this machine. Install it to let it take part in checks.", last_seen: "never", runs: 0, port: "-", can_read: false, can_run: false, can_answer: false },
    AgentInfo { name: "GitHub Copilot CLI", kind: "CLI", monogram: 'G', state: TagState::Live, state_label: "Connected", latency: "71 ms", allowed: true, detail: "Runs from PATH; reads the MCP server on localhost.", last_seen: "12 min ago", runs: 17, port: "7401", can_read: true, can_run: true, can_answer: false },
    AgentInfo { name: "Claude Desktop", kind: "Desktop app", monogram: 'D', state: TagState::Live, state_label: "Connected", latency: "36 ms", allowed: true, detail: "Desktop app with the Kriko extension installed.", last_seen: "just now", runs: 8, port: "7402", can_read: true, can_run: false, can_answer: true },
    AgentInfo { name: "Cursor", kind: "Desktop app", monogram: 'U', state: TagState::Done, state_label: "Idle", latency: "64 ms", allowed: true, detail: "Desktop app with the Kriko extension installed.", last_seen: "Yesterday", runs: 5, port: "7402", can_read: true, can_run: true, can_answer: false },
];

// ---- knowledge (browse) ----

pub struct KnowledgeRow {
    pub subject: &'static str,
    pub attribute: &'static str,
    pub value: &'static str,
    pub claims: u8,
    pub sources: u8,
    pub trust: TagState,
    pub trust_label: &'static str,
    pub evidence_for: &'static str,
    pub evidence_against: &'static str,
}

pub const KNOWLEDGE: &[KnowledgeRow] = &[
    KnowledgeRow { subject: "Product A earbuds", attribute: "Noise cancelling", value: "38 dB", claims: 2, sources: 5, trust: TagState::Done, trust_label: "Backed", evidence_for: "Two lab measurements agree at 38 dB.", evidence_against: "" },
    KnowledgeRow { subject: "Product B earbuds", attribute: "Battery, earbuds only", value: "6 h or 8 h", claims: 2, sources: 4, trust: TagState::Need, trust_label: "Disputed", evidence_for: "Vendor page says 8 h.", evidence_against: "A measured review found 6 h." },
    KnowledgeRow { subject: "Product C earbuds", attribute: "Codec support", value: "Not stated", claims: 0, sources: 0, trust: TagState::Queue, trust_label: "No evidence", evidence_for: "", evidence_against: "" },
    KnowledgeRow { subject: "Samsung Galaxy Buds2 Pro", attribute: "Water resistance", value: "IPX7", claims: 3, sources: 6, trust: TagState::Done, trust_label: "Backed", evidence_for: "Spec sheet and two reviews agree.", evidence_against: "" },
    KnowledgeRow { subject: "Apple iPhone 15", attribute: "Battery", value: "20 h video", claims: 2, sources: 5, trust: TagState::Done, trust_label: "Backed", evidence_for: "Tech specs and one measured test agree.", evidence_against: "" },
    KnowledgeRow { subject: "Volkswagen Passat 2020", attribute: "Boot capacity", value: "586 l", claims: 1, sources: 3, trust: TagState::Done, trust_label: "Backed", evidence_for: "Manufacturer figure, cited by two reviews.", evidence_against: "" },
    KnowledgeRow { subject: "Sony WH-1000XM5", attribute: "Noise cancelling", value: "30 dB, claimed", claims: 1, sources: 2, trust: TagState::Queue, trust_label: "No evidence", evidence_for: "", evidence_against: "" },
    KnowledgeRow { subject: "Toyota Corolla 2021", attribute: "Fuel economy", value: "6.4 l/100 km or 7.1", claims: 2, sources: 4, trust: TagState::Need, trust_label: "Disputed", evidence_for: "Cycle figure says 6.4.", evidence_against: "Owner logs average 7.1." },
];

// ---- sites ----

pub struct SiteRow {
    pub host: &'static str,
    pub pages: u16,
    pub claims: u16,
    pub trust: TagState,
    pub trust_label: &'static str,
}

pub const SITES: &[SiteRow] = &[
    SiteRow { host: "rtings.com", pages: 38, claims: 61, trust: TagState::Done, trust_label: "Backed" },
    SiteRow { host: "vendor.example", pages: 52, claims: 47, trust: TagState::Need, trust_label: "Disputed" },
    SiteRow { host: "forum.test", pages: 3, claims: 1, trust: TagState::Block, trust_label: "Blocked" },
    SiteRow { host: "notebookcheck.net", pages: 21, claims: 34, trust: TagState::Done, trust_label: "Backed" },
    SiteRow { host: "wikipedia.org", pages: 44, claims: 76, trust: TagState::Done, trust_label: "Backed" },
];

// ---- packs / overview ----

pub struct Pack {
    pub name: &'static str,
    pub subjects: u16,
    pub enabled: bool,
}

pub const PACKS: &[Pack] = &[
    Pack { name: "samsung.headphones", subjects: 38, enabled: true },
    Pack { name: "apple.iphone15", subjects: 22, enabled: true },
    Pack { name: "volkswagen.passat.2020", subjects: 17, enabled: false },
    Pack { name: "sony.headphones", subjects: 12, enabled: true },
];

// ---- local LLM ----

pub struct LocalModel {
    pub name: &'static str,
    pub size: &'static str,
    pub memory: &'static str,
    pub speed: u8,
    pub loaded: bool,
    /// How many billion parameters the model carries.
    pub params: &'static str,
    /// Quantization, the way the weights sit on disk.
    pub quant: &'static str,
    /// Context window the model can hold at once.
    pub ctx: &'static str,
    /// Whether the model fits in this machine's VRAM as-is.
    pub fits: bool,
    /// What the model is best at, one line.
    pub note: &'static str,
}

pub const MODELS: &[LocalModel] = &[
    LocalModel { name: "llama3.2-3b-instruct", size: "2.0 GB", memory: "3.4 GB", speed: 71, loaded: true, params: "3.2 B", quant: "Q4_K_M", ctx: "128 k", fits: true, note: "Fast grounding passes; the default." },
    LocalModel { name: "qwen2.5-7b-instruct", size: "4.7 GB", memory: "6.9 GB", speed: 43, loaded: false, params: "7.6 B", quant: "Q4_K_M", ctx: "32 k", fits: true, note: "Slower, better at long pages." },
    LocalModel { name: "phi-3.5-mini", size: "2.2 GB", memory: "3.1 GB", speed: 66, loaded: false, params: "3.8 B", quant: "Q4_0", ctx: "128 k", fits: true, note: "Small and quick on short text." },
    LocalModel { name: "mistral-nemo-12b", size: "7.1 GB", memory: "9.8 GB", speed: 29, loaded: false, params: "12.2 B", quant: "Q4_K_M", ctx: "128 k", fits: false, note: "Best answers; needs most of the VRAM." },
];

/// The machine the local server runs on.
pub const GPU_NAME: &str = "NVIDIA RTX 3060 Laptop";
pub const GPU_VRAM_TOTAL: &str = "10.0 GB";
pub const GPU_VRAM_USED: &str = "5.8 GB";

/// The lines the simulated grounding pass returns when the model is tested.
pub const LOCAL_TEST_LINES: &[&str] = &[
    "The model answered in 1.8 s on this machine.",
    "It grounded 3 claims against stored evidence, 2 backed, 1 disputed.",
    "No claim left this machine to be answered.",
];

// ---- benchmark ----

pub struct BenchRun {
    pub label: &'static str,
    pub took: &'static str,
    pub value: u8,
}

pub const BENCH_RUNS: &[BenchRun] = &[
    BenchRun { label: "Grounding pass", took: "1 min 12", value: 86 },
    BenchRun { label: "Full check, 3 subjects", took: "3 min 05", value: 62 },
    BenchRun { label: "Full check, 8 subjects", took: "7 min 41", value: 38 },
    BenchRun { label: "Claim settling", took: "2 min 18", value: 74 },
    BenchRun { label: "Local LLM pass", took: "5 min 02", value: 51 },
];

// ---- the live actions dock ----

/// What an agent is doing right now, for the WORKING NOW lanes.
pub struct DockLane {
    pub agent: usize,
    pub task: &'static str,
    pub progress: u8,
}

pub const DOCK_LANES: &[DockLane] = &[
    DockLane { agent: 0, task: "Reading rtings.com/buds2-pro", progress: 62 },
    DockLane { agent: 1, task: "Grounding 3 claims on Buds2 Pro", progress: 38 },
    DockLane { agent: 4, task: "Waiting for claims to settle", progress: 12 },
];

/// A question an agent is holding for you, answerable from the dock.
pub struct DockRequest {
    pub agent: usize,
    pub text: &'static str,
    /// The word on the key that answers it.
    pub answer: &'static str,
}

pub const DOCK_REQUESTS: &[DockRequest] = &[
    DockRequest { agent: 2, text: "Sign in so it can take part in checks", answer: "Sign in" },
    DockRequest { agent: 0, text: "Allow rtings.com to be read for evidence", answer: "Allow" },
    DockRequest { agent: 1, text: "Approve the run on Product B earbuds", answer: "Approve" },
];

// ---- compare ----

/// How serious a recorded risk is.
#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Severity {
    Minor,
    Serious,
    Critical,
}

impl Severity {
    pub fn word(self) -> &'static str {
        match self {
            Severity::Minor => "MINOR",
            Severity::Serious => "SERIOUS",
            Severity::Critical => "CRITICAL",
        }
    }
}

/// One specification row cell: the value, how many sources hold it, and
/// whether every source agrees (`None` = not recorded at all).
#[derive(Clone, Copy)]
pub struct SpecCell {
    pub value: &'static str,
    pub sources: u8,
    pub backed: Option<bool>,
}

/// One risk row cell: `None` = no installed catalog holds this risk for this
/// product; `Some` = the severity and one line of evidence.
#[derive(Clone, Copy)]
pub struct RiskCell {
    pub severity: Option<Severity>,
    pub body: &'static str,
    pub sources: u8,
}

/// A subject that can sit in a compare slot: index into CHECKS plus the
/// specifications and the known risks, cell by cell.
pub struct CompareSubject {
    pub check: usize,
    pub specs: &'static [(&'static str, &'static [SpecCell])],
    pub risks: &'static [(&'static str, &'static [RiskCell])],
}

macro_rules! spec {
    ($label:literal, [$($v:literal, $s:literal, $b:expr,)*]) => {
        ($label, &[$(SpecCell { value: $v, sources: $s, backed: $b },)*])
    };
}

macro_rules! risk {
    ($label:literal, [$(($sev:expr, $body:literal, $s:literal),)*]) => {
        ($label, &[$(RiskCell { severity: $sev, body: $body, sources: $s },)*])
    };
}

pub const COMPARE_SUBJECTS: &[CompareSubject] = &[
    // Samsung Galaxy Buds2 Pro (CHECKS[0])
    CompareSubject {
        check: 0,
        specs: &[
            spec!("Noise cancelling", ["38 dB, measured", 5, Some(true),]),
            spec!("Battery, earbuds only", ["6 h", 4, Some(true),]),
            spec!("Water resistance", ["IPX7", 3, Some(true),]),
            spec!("Weight, per earbud", ["5.5 g", 2, Some(true),]),
            spec!("Price, typical", ["Mid", 6, Some(true),]),
            spec!("Codec support", ["Not stated", 0, None,]),
        ],
        risks: &[
            risk!("Battery swelling after a year", [(Some(Severity::Minor), "A few forum threads, no measured report.", 3),]),
            risk!("Case hinge cracks", [(Some(Severity::Serious), "One warranty report per 400 units, seller-sourced.", 2),]),
            risk!("Firmware locks ANC to Samsung phones", [(Some(Severity::Minor), "Documented by two reviews.", 4),]),
        ],
    },
    // Samsung Galaxy Buds Pro (CHECKS[1])
    CompareSubject {
        check: 1,
        specs: &[
            spec!("Noise cancelling", ["33 dB, claimed", 2, Some(false),]),
            spec!("Battery, earbuds only", ["8 h, sources disagree", 4, Some(false),]),
            spec!("Water resistance", ["IPX4", 3, Some(true),]),
            spec!("Weight, per earbud", ["5.4 g", 1, Some(true),]),
            spec!("Price, typical", ["Low", 5, Some(true),]),
            spec!("Codec support", ["Not stated", 0, None,]),
        ],
        risks: &[
            risk!("Battery swelling after a year", [(Some(Severity::Serious), "Measured in one long-term review.", 5),]),
            risk!("Case hinge cracks", [(Some(Severity::Minor), "Two forum threads only.", 2),]),
            risk!("Firmware locks ANC to Samsung phones", [(Some(Severity::Minor), "Documented by two reviews.", 4),]),
        ],
    },
    // Samsung Galaxy Buds Live (CHECKS[2])
    CompareSubject {
        check: 2,
        specs: &[
            spec!("Noise cancelling", ["None", 3, Some(true),]),
            spec!("Battery, earbuds only", ["5 h", 2, Some(true),]),
            spec!("Water resistance", ["IPX2", 2, Some(true),]),
            spec!("Weight, per earbud", ["5.6 g", 1, Some(true),]),
            spec!("Price, typical", ["Low", 4, Some(true),]),
            spec!("Codec support", ["Not stated", 0, None,]),
        ],
        risks: &[
            risk!("Battery swelling after a year", [(Some(Severity::Critical), "Classified in two warranty reports.", 6),]),
            risk!("Case hinge cracks", [(Some(Severity::Serious), "Recurring in the 2021 batch.", 4),]),
        ],
    },
    // Apple iPhone 15 (CHECKS[3])
    CompareSubject {
        check: 3,
        specs: &[
            spec!("Battery, video playback", ["20 h", 5, Some(true),]),
            spec!("Water resistance", ["IP68", 4, Some(true),]),
            spec!("Weight", ["171 g", 3, Some(true),]),
            spec!("Price, typical", ["High", 7, Some(true),]),
            spec!("Codec support", ["AAC only", 2, Some(true),]),
        ],
        risks: &[
            risk!("Battery health drops fast when hot", [(Some(Severity::Minor), "Owner logs agree on slower months.", 4),]),
            risk!("Repair parts are expensive", [(Some(Severity::Serious), "Screen costs a third of the phone.", 3),]),
        ],
    },
    // Sony WH-1000XM5 (CHECKS[5])
    CompareSubject {
        check: 5,
        specs: &[
            spec!("Noise cancelling", ["42 dB, measured", 6, Some(true),]),
            spec!("Battery, earbuds only", ["30 h, over-ear", 5, Some(true),]),
            spec!("Water resistance", ["None", 3, Some(true),]),
            spec!("Weight, per earbud", ["250 g, over-ear", 2, Some(true),]),
            spec!("Price, typical", ["High", 6, Some(true),]),
            spec!("Codec support", ["LDAC", 4, Some(true),]),
        ],
        risks: &[
            risk!("No water resistance at all", [(Some(Severity::Serious), "Sweat can kill the left driver.", 5),]),
            risk!("Ear pads wear out in two years", [(Some(Severity::Minor), "Replacements are cheap.", 6),]),
        ],
    },
];

/// A saved, named comparison. The indexes point into CHECKS.
pub struct CompareDraft {
    pub name: &'static str,
    pub slots: &'static [usize],
}

pub const COMPARE_DRAFTS: &[CompareDraft] = &[
    CompareDraft { name: "Earbuds shortlist", slots: &[0, 1, 5] },
    CompareDraft { name: "Buds2 Pro vs Buds Pro", slots: &[0, 1] },
    CompareDraft { name: "Car and phone", slots: &[3, 4] },
];

/// Suggested follow-up questions, pressed straight from the table.
pub const COMPARE_SUGGESTIONS: &[&str] = &[
    "Which of these has the fewest serious risks?",
    "Which one is the cheapest to fix, and why?",
    "What is the single biggest difference between them?",
    "Which would you buy and why?",
];

/// The slots the screen opens with: the earbuds shortlist.
pub const COMPARE_DEFAULT_SLOTS: &[usize] = &[0, 1, 5];
