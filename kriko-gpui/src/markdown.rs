//! Markdown for an answer.
//!
//! The engine's agents write markdown: `**bold**` for a term, `- ` for a list,
//! a `|` table for a comparison, `[words](url)` for a page, `` `code` `` for a
//! literal. The screen used to draw that text as one wrapped run of words, so
//! every asterisk, pipe and bracket reached the reader as a character. This
//! module reads the text into blocks and spans, and draws each one as the
//! thing it says it is.
//!
//! Two rules hold everywhere below.
//!
//! **Nothing is dropped.** A construct the reader did not intend as markdown
//! (an asterisk in a part number, a pipe in a quote) must survive as text. The
//! parser only recognises a construct it can close, and a line it cannot read
//! becomes a paragraph exactly as written.
//!
//! **Nothing here executes or fetches.** A link is a string that the caller
//! decides whether to open. `markdown` never calls `open_url`.

use gpui::{div, prelude::*, px, AnyElement, Context, Div, FontWeight, SharedString, Styled};

use crate::app::Kriko;
use crate::theme::*;

// ---- the model ----

/// One piece of a line, with the emphasis it carries.
#[derive(Clone, Debug, PartialEq)]
pub struct Span {
    pub text: String,
    pub bold: bool,
    pub italic: bool,
    pub code: bool,
    /// The address a link opens. Empty for every other span.
    pub url: String,
}

impl Span {
    fn plain(text: impl Into<String>) -> Span {
        Span { text: text.into(), bold: false, italic: false, code: false, url: String::new() }
    }

    pub fn is_link(&self) -> bool {
        !self.url.is_empty()
    }
}

/// One block of an answer.
#[derive(Clone, Debug, PartialEq)]
pub enum Block {
    /// `# ` through `###### `.
    Heading { level: usize, spans: Vec<Span> },
    Paragraph { spans: Vec<Span> },
    /// `- `, `* `, `+ `, or `1. `. `start` is the first ordinal for an ordered
    /// list, so a list that begins at 3 keeps its 3.
    List { ordered: bool, start: u64, items: Vec<ListItem> },
    /// A fenced block. `language` is the word after the fence, lowercased.
    Code { language: String, text: String },
    /// `> `.
    Quote { lines: Vec<Vec<Span>> },
    /// A `|` table. `head` is empty for a table with no header row.
    Table { head: Vec<Vec<Span>>, rows: Vec<Vec<Vec<Span>>> },
    /// `---`.
    Rule,
}

/// One list item: its own spans, and any lines that belong to it.
#[derive(Clone, Debug, PartialEq)]
pub struct ListItem {
    pub spans: Vec<Span>,
    /// The item's continuation lines, each its own run of spans.
    pub rest: Vec<Vec<Span>>,
}

/// The blocks of one answer.
pub fn parse(text: &str) -> Vec<Block> {
    let normalised = text.replace("\r\n", "\n").replace('\r', "\n");
    let lines: Vec<&str> = normalised.split('\n').collect();
    let mut blocks = Vec::new();
    let mut i = 0usize;

    while i < lines.len() {
        let line = lines[i];

        if line.trim().is_empty() {
            i += 1;
            continue;
        }

        // A fence opens a literal block: everything to its close is text.
        if let Some(language) = fence_open(line) {
            let mut body: Vec<&str> = Vec::new();
            i += 1;
            while i < lines.len() && !is_fence(lines[i]) {
                body.push(lines[i]);
                i += 1;
            }
            // The closing fence, when there is one.
            if i < lines.len() {
                i += 1;
            }
            blocks.push(Block::Code { language, text: body.join("\n") });
            continue;
        }

        if is_rule(line) {
            blocks.push(Block::Rule);
            i += 1;
            continue;
        }

        if let Some((level, rest)) = heading(line) {
            blocks.push(Block::Heading { level, spans: inline(rest) });
            i += 1;
            continue;
        }

        // A table needs its separator row, so a lone pipe is prose.
        if let Some((head, rows, consumed)) = table(&lines[i..]) {
            blocks.push(Block::Table { head, rows });
            i += consumed;
            continue;
        }

        if let Some(marker) = list_marker(line) {
            let ordered = marker.ordered;
            let start = marker.start;
            let mut items: Vec<ListItem> = Vec::new();
            while i < lines.len() {
                let Some(next) = list_marker(lines[i]) else { break };
                if next.ordered != ordered {
                    break;
                }
                let mut item = ListItem { spans: inline(next.rest), rest: Vec::new() };
                i += 1;
                // A deeper indent continues the item; a blank line or a new
                // block ends it.
                while i < lines.len() {
                    let cont = lines[i];
                    if cont.trim().is_empty() {
                        break;
                    }
                    if list_marker(cont).is_some() || heading(cont).is_some() || is_rule(cont) {
                        break;
                    }
                    if !cont.starts_with("  ") && !cont.starts_with('\t') {
                        break;
                    }
                    item.rest.push(inline(cont.trim()));
                    i += 1;
                }
                items.push(item);
            }
            blocks.push(Block::List { ordered, start, items });
            continue;
        }

        if line.trim_start().starts_with('>') {
            let mut quoted: Vec<Vec<Span>> = Vec::new();
            while i < lines.len() {
                let Some(next) = lines[i].trim_start().strip_prefix('>') else { break };
                quoted.push(inline(next.trim_start()));
                i += 1;
            }
            blocks.push(Block::Quote { lines: quoted });
            continue;
        }

        // A paragraph runs to the next blank line or the next block.
        let mut para: Vec<&str> = Vec::new();
        while i < lines.len() {
            let next = lines[i];
            if next.trim().is_empty()
                || fence_open(next).is_some()
                || is_rule(next)
                || heading(next).is_some()
                || list_marker(next).is_some()
                || next.trim_start().starts_with('>')
            {
                break;
            }
            para.push(next.trim());
            i += 1;
        }
        if para.is_empty() {
            // A line that opened a block the branch above did not take.
            para.push(line.trim());
            i += 1;
        }
        blocks.push(Block::Paragraph { spans: inline(&para.join(" ")) });
    }

    blocks
}

// ---- block recognition ----

fn fence_open(line: &str) -> Option<String> {
    let trimmed = line.trim_start();
    let fence: String = trimmed.chars().take_while(|c| *c == '`' || *c == '~').collect();
    if fence.len() < 3 {
        return None;
    }
    let first = fence.chars().next()?;
    if fence.chars().any(|c| c != first) {
        return None;
    }
    Some(trimmed[fence.len()..].trim().to_ascii_lowercase())
}

fn is_fence(line: &str) -> bool {
    fence_open(line).is_some()
}

fn is_rule(line: &str) -> bool {
    let t = line.trim();
    let body: String = t.chars().filter(|c| !c.is_whitespace()).collect();
    body.len() >= 3 && body.chars().all(|c| c == '-')
}

fn heading(line: &str) -> Option<(usize, &str)> {
    let t = line.trim_start();
    let hashes = t.chars().take_while(|c| *c == '#').count();
    if hashes == 0 || hashes > 6 {
        return None;
    }
    let rest = &t[hashes..];
    // `#tag` is a word, not a heading.
    if !rest.is_empty() && !rest.starts_with(' ') {
        return None;
    }
    Some((hashes, rest.trim()))
}

struct Marker<'a> {
    ordered: bool,
    start: u64,
    rest: &'a str,
}

fn list_marker(line: &str) -> Option<Marker<'_>> {
    let indent = line.len() - line.trim_start().len();
    // A tab counts as up to four columns; anything past one level is a
    // continuation, which the item's own loop reads.
    if indent > 6 {
        return None;
    }
    let t = line.trim_start();
    for bullet in ["- ", "* ", "+ "] {
        if let Some(rest) = t.strip_prefix(bullet) {
            return Some(Marker { ordered: false, start: 1, rest: rest.trim() });
        }
    }
    // `-` alone on a line is an empty item, not a rule (a rule is three).
    if t == "-" || t == "*" || t == "+" {
        return Some(Marker { ordered: false, start: 1, rest: "" });
    }
    let digits: String = t.chars().take_while(|c| c.is_ascii_digit()).collect();
    if digits.is_empty() || digits.len() > 9 {
        return None;
    }
    let after = &t[digits.len()..];
    for sep in [". ", ") "] {
        if let Some(rest) = after.strip_prefix(sep) {
            let start = digits.parse::<u64>().unwrap_or(1);
            return Some(Marker { ordered: true, start, rest: rest.trim() });
        }
    }
    None
}

/// A table: a header row, a separator row, then body rows.
fn table(lines: &[&str]) -> Option<(Vec<Vec<Span>>, Vec<Vec<Vec<Span>>>, usize)> {
    if lines.len() < 2 {
        return None;
    }
    let head = split_row(lines[0])?;
    let align = split_row(lines[1])?;
    if align.is_empty() || !align.iter().all(|cell| is_separator_cell(cell)) {
        return None;
    }
    let mut rows: Vec<Vec<Vec<Span>>> = Vec::new();
    let mut consumed = 2usize;
    for line in &lines[2..] {
        if line.trim().is_empty() {
            break;
        }
        let Some(cells) = split_row(line) else { break };
        rows.push(cells);
        consumed += 1;
    }
    Some((head, rows, consumed))
}

/// Split one `| a | b |` row. `None` when the line is not a row at all.
fn split_row(line: &str) -> Option<Vec<Vec<Span>>> {
    let t = line.trim();
    if !t.contains('|') {
        return None;
    }
    let t = t.strip_prefix('|').unwrap_or(t);
    let t = t.strip_suffix('|').unwrap_or(t);
    // A cell that is only a pipe would split to nothing; keep every cell,
    // because a table's columns are positional.
    let cells: Vec<Vec<Span>> = t.split('|').map(|cell| inline(cell.trim())).collect();
    if cells.len() < 2 {
        return None;
    }
    Some(cells)
}

fn is_separator_cell(cell: &[Span]) -> bool {
    if cell.len() != 1 {
        return false;
    }
    let text = cell[0].text.trim();
    let body: String = text.chars().filter(|c| *c != ' ').collect();
    !body.is_empty() && body.chars().all(|c| c == '-' || c == ':')
}

// ---- inline ----

/// One line's spans: emphasis, code, and links, with every other character
/// kept as it was written.
pub fn inline(text: &str) -> Vec<Span> {
    let mut out: Vec<Span> = Vec::new();
    let mut plain = String::new();
    let chars: Vec<char> = text.chars().collect();
    let mut i = 0usize;

    // `push` flushes the pending plain run first, so spans keep their order.
    macro_rules! flush {
        () => {
            if !plain.is_empty() {
                out.push(Span::plain(std::mem::take(&mut plain)));
            }
        };
    }

    while i < chars.len() {
        let c = chars[i];

        // `` `code` ``
        if c == '`' {
            let fence: usize = chars[i..].iter().take_while(|x| **x == '`').count();
            if let Some(end) = find_run(&chars, i + fence, '`', fence) {
                flush!();
                let body: String = chars[i + fence..end].iter().collect();
                out.push(Span { text: body.trim().to_string(), bold: false, italic: false, code: true, url: String::new() });
                i = end + fence;
                continue;
            }
            plain.push(c);
            i += 1;
            continue;
        }

        // `[words](url)`
        if c == '[' {
            if let Some((label, url, next)) = link(&chars, i) {
                flush!();
                let mut spans = inline(&label);
                for span in spans.iter_mut() {
                    span.url = url.clone();
                }
                out.append(&mut spans);
                i = next;
                continue;
            }
            plain.push(c);
            i += 1;
            continue;
        }

        // `**bold**` and `*italic*`, or `__bold__` and `_italic_`.
        if c == '*' || c == '_' {
            let run: usize = chars[i..].iter().take_while(|x| **x == c).count();
            let width = if run >= 2 { 2 } else { 1 };
            if let Some(end) = find_run(&chars, i + width, c, width) {
                // A marker with nothing between it is text, not emphasis.
                let body: String = chars[i + width..end].iter().collect();
                if !body.trim().is_empty() {
                    flush!();
                    let mut spans = inline(&body);
                    for span in spans.iter_mut() {
                        if width == 2 {
                            span.bold = true;
                        } else {
                            span.italic = true;
                        }
                    }
                    out.append(&mut spans);
                    i = end + width;
                    continue;
                }
            }
            for _ in 0..run {
                plain.push(c);
            }
            i += run;
            continue;
        }

        plain.push(c);
        i += 1;
    }
    flush!();
    out
}

/// The index where a run of exactly `width` of `marker` starts, at or after
/// `from`. `None` when there is no such run.
fn find_run(chars: &[char], from: usize, marker: char, width: usize) -> Option<usize> {
    let mut i = from;
    while i < chars.len() {
        if chars[i] == marker {
            let run: usize = chars[i..].iter().take_while(|x| **x == marker).count();
            if run >= width {
                return Some(i);
            }
            i += run;
            continue;
        }
        i += 1;
    }
    None
}

/// `[label](url)` at `at`, as `(label, url, index after the close)`.
fn link(chars: &[char], at: usize) -> Option<(String, String, usize)> {
    let mut depth = 0usize;
    let mut close = None;
    let mut i = at;
    while i < chars.len() {
        match chars[i] {
            '[' => depth += 1,
            ']' => {
                depth -= 1;
                if depth == 0 {
                    close = Some(i);
                    break;
                }
            }
            _ => {}
        }
        i += 1;
    }
    let close = close?;
    if chars.get(close + 1) != Some(&'(') {
        return None;
    }
    let mut depth = 0usize;
    let mut end = None;
    let mut j = close + 1;
    while j < chars.len() {
        match chars[j] {
            '(' => depth += 1,
            ')' => {
                depth -= 1;
                if depth == 0 {
                    end = Some(j);
                    break;
                }
            }
            _ => {}
        }
        j += 1;
    }
    let end = end?;
    let label: String = chars[at + 1..close].iter().collect();
    let target: String = chars[close + 2..end].iter().collect();
    let url = normalise_url(&target);
    if url.is_empty() {
        return None;
    }
    Some((label, url, end + 1))
}

/// A link target, or "" when it is not one this app will open. Only `http`,
/// `https` and `mailto` are offered: a markdown answer is model output, and a
/// `javascript:` or `file:` target is not something a reader asked to open.
pub fn normalise_url(target: &str) -> String {
    let t = target.trim().trim_matches(['<', '>']);
    let lower = t.to_ascii_lowercase();
    for scheme in ["http://", "https://", "mailto:"] {
        if lower.starts_with(scheme) {
            return t.to_string();
        }
    }
    String::new()
}

// ---- drawing ----

/// The answer's blocks, drawn. Each block is a selectable run, so a reader can
/// take a part number or a quotation out of an answer, and each link inside it
/// opens the page it names.
pub fn view(
    text: &str,
    id: &str,
    motion: bool,
    selection: &gpui::Entity<crate::select::Selection>,
    cx: &mut Context<Kriko>,
) -> Div {
    let blocks = parse(text);
    let mut column = div().flex().flex_col().gap(px(SPACE_M)).min_w(px(0.0)).w_full();
    if blocks.is_empty() {
        return column;
    }
    for (index, block) in blocks.into_iter().enumerate() {
        let key = format!("{id}-b{index}");
        let drawn = block_view(block, &key, selection, cx);
        column = column.child(arrive(drawn, key, motion));
    }
    column
}

fn block_view(
    block: Block,
    key: &str,
    selection: &gpui::Entity<crate::select::Selection>,
    cx: &mut Context<Kriko>,
) -> AnyElement {
    match block {
        Block::Heading { level, spans } => heading_view(level, spans, key, selection, cx),
        Block::Paragraph { spans } => run(
            spans,
            key,
            14.5,
            23.0,
            INK_2,
            FontWeight::NORMAL,
            SANS,
            0.0,
            selection,
            cx,
        ),
        Block::List { ordered, start, items } => {
            list_view(ordered, start, items, key, selection, cx)
        }
        Block::Code { language, text } => code_view(&language, &text, key, selection, cx),
        Block::Quote { lines } => quote_view(lines, key, selection, cx),
        Block::Table { head, rows } => table_view(head, rows, key, selection, cx),
        Block::Rule => div()
            .w_full()
            .h(px(1.0))
            .my(px(SPACE_XS))
            .bg(paint_a(HAIRLINE))
            .into_any_element(),
    }
}

/// One paragraph-like run of spans: the common case, and the one a reader
/// selects most.
#[allow(clippy::too_many_arguments)]
fn run(
    spans: Vec<Span>,
    key: &str,
    size: f32,
    leading: f32,
    colour: u32,
    weight: FontWeight,
    family: &'static str,
    indent: f32,
    selection: &gpui::Entity<crate::select::Selection>,
    cx: &mut Context<Kriko>,
) -> AnyElement {
    let pieces = pieces_of(spans, size, colour, weight, family);
    div()
        .w_full()
        .min_w(px(0.0))
        .when(indent > 0.0, |d| d.pl(px(indent)))
        .child(
            crate::select::Selectable::new(
                gpui::ElementId::Name(SharedString::from(key.to_string())),
                pieces,
                leading,
                selection.clone(),
                cx,
            )
            .interactive(selection.clone()),
        )
        .into_any_element()
}

/// A run's spans as the pieces the selectable element draws.
fn pieces_of(
    spans: Vec<Span>,
    size: f32,
    colour: u32,
    weight: FontWeight,
    family: &'static str,
) -> Vec<crate::select::Piece> {
    let mut pieces = Vec::new();
    for span in spans {
        if span.text.is_empty() {
            continue;
        }
        let mut piece = if span.code {
            crate::select::Piece::new(span.text, ICE, size - 1.5).family(CODE)
        } else if span.is_link() {
            crate::select::Piece::new(span.text, BRAND_BRIGHT, size).link(span.url)
        } else {
            crate::select::Piece::new(span.text, colour, size).family(family)
        };
        piece = if span.bold { piece.bold() } else { piece.weight(weight) };
        if span.italic {
            piece = piece.italic();
        }
        pieces.push(piece);
    }
    if pieces.is_empty() {
        pieces.push(crate::select::Piece::new(" ", colour, size));
    }
    pieces
}

fn heading_view(
    level: usize,
    spans: Vec<Span>,
    key: &str,
    selection: &gpui::Entity<crate::select::Selection>,
    cx: &mut Context<Kriko>,
) -> AnyElement {
    let (size, leading) = match level {
        1 => (19.0, 27.0),
        2 => (17.0, 25.0),
        3 => (15.5, 23.0),
        _ => (14.5, 22.0),
    };
    let drawn = run(
        spans,
        key,
        size,
        leading,
        INK,
        FontWeight::SEMIBOLD,
        DISPLAY,
        0.0,
        selection,
        cx,
    );
    div()
        .w_full()
        .min_w(px(0.0))
        .when(level > 2, |d| d.pt(px(SPACE_XS)))
        .child(drawn)
        .into_any_element()
}

fn list_view(
    ordered: bool,
    start: u64,
    items: Vec<ListItem>,
    key: &str,
    selection: &gpui::Entity<crate::select::Selection>,
    cx: &mut Context<Kriko>,
) -> AnyElement {
    let mut column = div().flex().flex_col().gap(px(SPACE_S)).w_full().min_w(px(0.0));
    for (index, item) in items.into_iter().enumerate() {
        let marker = if ordered {
            format!("{}.", start + index as u64)
        } else {
            "•".to_string()
        };
        let mut body = div().flex().flex_col().gap(px(SPACE_XS)).flex_1().min_w(px(0.0));
        body = body.child(run(
            item.spans,
            &format!("{key}-i{index}"),
            14.5,
            23.0,
            INK_2,
            FontWeight::NORMAL,
            SANS,
            0.0,
            selection,
            cx,
        ));
        for (line_index, line) in item.rest.into_iter().enumerate() {
            body = body.child(run(
                line,
                &format!("{key}-i{index}-c{line_index}"),
                14.5,
                23.0,
                INK_2,
                FontWeight::NORMAL,
                SANS,
                0.0,
                selection,
                cx,
            ));
        }
        column = column.child(
            div()
                .flex()
                .items_start()
                .gap(px(SPACE_S))
                .w_full()
                .min_w(px(0.0))
                .child(
                    div()
                        .flex_none()
                        .min_w(px(18.0))
                        .pt(px(2.0))
                        .font_family(SANS)
                        .text_size(px(13.0))
                        .line_height(px(20.0))
                        .text_color(paint(MUTED))
                        .child(marker),
                )
                .child(body),
        );
    }
    column.into_any_element()
}

fn code_view(
    language: &str,
    text: &str,
    key: &str,
    selection: &gpui::Entity<crate::select::Selection>,
    cx: &mut Context<Kriko>,
) -> AnyElement {
    let mut block = div()
        .flex()
        .flex_col()
        .gap(px(SPACE_XS))
        .w_full()
        .min_w(px(0.0))
        .rounded(px(10.0))
        .bg(paint(WELL))
        .border_1()
        .border_color(paint_a(HAIRLINE))
        .p(px(SPACE_M))
        .overflow_hidden();
    if !language.is_empty() {
        block = block.child(
            div()
                .font_family(SANS)
                .font_weight(FontWeight::MEDIUM)
                .text_size(px(11.0))
                .text_color(paint(DIM))
                .child(language.to_uppercase()),
        );
    }
    // A literal is copied as a whole, so its selection is one run over the
    // block's own text rather than a run per line.
    let pieces = vec![crate::select::Piece::new(text.to_string(), INK_2, 12.5).family(CODE)];
    block
        .child(
            crate::select::Selectable::new(
                gpui::ElementId::Name(SharedString::from(format!("{key}-code"))),
                pieces,
                19.0,
                selection.clone(),
                cx,
            )
            .interactive(selection.clone()),
        )
        .into_any_element()
}

fn quote_view(
    lines: Vec<Vec<Span>>,
    key: &str,
    selection: &gpui::Entity<crate::select::Selection>,
    cx: &mut Context<Kriko>,
) -> AnyElement {
    let mut body = div().flex().flex_col().gap(px(SPACE_XS)).flex_1().min_w(px(0.0));
    for (index, line) in lines.into_iter().enumerate() {
        body = body.child(run(
            line,
            &format!("{key}-q{index}"),
            14.0,
            22.0,
            MUTED,
            FontWeight::NORMAL,
            SANS,
            0.0,
            selection,
            cx,
        ));
    }
    div()
        .flex()
        .items_start()
        .gap(px(SPACE_M))
        .w_full()
        .min_w(px(0.0))
        .child(div().flex_none().w(px(2.0)).rounded(px(1.0)).bg(paint_a(BRAND_WASH)))
        .child(body)
        .into_any_element()
}

fn table_view(
    head: Vec<Vec<Span>>,
    rows: Vec<Vec<Vec<Span>>>,
    key: &str,
    selection: &gpui::Entity<crate::select::Selection>,
    cx: &mut Context<Kriko>,
) -> AnyElement {
    let columns = head
        .len()
        .max(rows.iter().map(Vec::len).max().unwrap_or(0))
        .max(1);
    let mut table = div()
        .flex()
        .flex_col()
        .w_full()
        .min_w(px(0.0))
        .rounded(px(10.0))
        .border_1()
        .border_color(paint_a(HAIRLINE))
        .overflow_hidden();

    if !head.is_empty() {
        table = table.child(table_row(head, columns, true, 0, key, selection, cx));
    }
    for (index, row) in rows.into_iter().enumerate() {
        table = table.child(table_row(row, columns, false, index, key, selection, cx));
    }
    table.into_any_element()
}

#[allow(clippy::too_many_arguments)]
fn table_row(
    cells: Vec<Vec<Span>>,
    columns: usize,
    header: bool,
    index: usize,
    key: &str,
    selection: &gpui::Entity<crate::select::Selection>,
    cx: &mut Context<Kriko>,
) -> AnyElement {
    let mut row = div()
        .flex()
        .w_full()
        .min_w(px(0.0))
        .when(index % 2 == 1 && !header, |d| d.bg(paint_a(GLASS_1)))
        .when(header, |d| d.bg(paint(WELL)));
    for column in 0..columns {
        let spans = cells.get(column).cloned().unwrap_or_default();
        let cell = run(
            spans,
            &format!("{key}-r{index}-c{column}"),
            13.0,
            20.0,
            if header { INK } else { INK_2 },
            if header { FontWeight::SEMIBOLD } else { FontWeight::NORMAL },
            SANS,
            0.0,
            selection,
            cx,
        );
        row = row.child(
            div()
                .flex_1()
                .min_w(px(0.0))
                .px(px(SPACE_M))
                .py(px(SPACE_S))
                .when(column > 0, |d| d.border_l_1().border_color(paint_a(HAIRLINE)))
                .child(cell),
        );
    }
    row.into_any_element()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn text_of(spans: &[Span]) -> String {
        spans.iter().map(|s| s.text.as_str()).collect()
    }

    #[test]
    fn a_bold_term_is_one_bold_span_and_the_asterisks_are_gone() {
        let spans = inline("the **oil filter** is here");
        assert_eq!(text_of(&spans), "the oil filter is here");
        assert!(spans.iter().any(|s| s.bold && s.text == "oil filter"));
        assert!(!text_of(&spans).contains('*'));
    }

    #[test]
    fn an_unclosed_asterisk_survives_as_text() {
        let spans = inline("a 5*3 wheel");
        assert_eq!(text_of(&spans), "a 5*3 wheel");
        assert!(spans.iter().all(|s| !s.bold));
    }

    #[test]
    fn a_lone_asterisk_pair_keeps_its_characters() {
        // A part number is not emphasis.
        assert_eq!(text_of(&inline("K9K*")), "K9K*");
        assert_eq!(text_of(&inline("2 * 4 = 8")), "2 * 4 = 8");
    }

    #[test]
    fn a_markdown_link_keeps_its_words_and_carries_its_address() {
        let spans = inline("see [the manual](https://example.com/a.pdf) now");
        assert_eq!(text_of(&spans), "see the manual now");
        let link = spans.iter().find(|s| s.is_link()).expect("a link");
        assert_eq!(link.text, "the manual");
        assert_eq!(link.url, "https://example.com/a.pdf");
    }

    #[test]
    fn a_target_this_app_will_not_open_is_left_as_words() {
        let spans = inline("[click](javascript:alert(1))");
        assert!(spans.iter().all(|s| !s.is_link()));
    }

    #[test]
    fn inline_code_keeps_its_literal() {
        let spans = inline("use `RN17` here");
        assert_eq!(text_of(&spans), "use RN17 here");
        assert!(spans.iter().any(|s| s.code && s.text == "RN17"));
    }

    #[test]
    fn a_heading_is_its_own_block_with_its_level() {
        let blocks = parse("# Engine oil\n\nsome words");
        assert_eq!(blocks.len(), 2);
        match &blocks[0] {
            Block::Heading { level, spans } => {
                assert_eq!(*level, 1);
                assert_eq!(text_of(spans), "Engine oil");
            }
            other => panic!("expected a heading, got {other:?}"),
        }
        assert!(matches!(&blocks[1], Block::Paragraph { .. }));
    }

    #[test]
    fn a_hash_inside_a_word_is_not_a_heading() {
        let blocks = parse("#K9K filter");
        assert!(matches!(&blocks[0], Block::Paragraph { .. }));
    }

    #[test]
    fn a_bullet_list_keeps_its_items_apart() {
        let blocks = parse("- first\n- second\n- third");
        match &blocks[0] {
            Block::List { ordered, items, .. } => {
                assert!(!ordered);
                assert_eq!(items.len(), 3);
                assert_eq!(text_of(&items[1].spans), "second");
            }
            other => panic!("expected a list, got {other:?}"),
        }
    }

    #[test]
    fn an_ordered_list_keeps_the_number_it_started_at() {
        let blocks = parse("3. three\n4. four");
        match &blocks[0] {
            Block::List { ordered, start, items } => {
                assert!(ordered);
                assert_eq!(*start, 3);
                assert_eq!(items.len(), 2);
            }
            other => panic!("expected a list, got {other:?}"),
        }
    }

    #[test]
    fn a_table_needs_its_separator_row() {
        let with = parse("| Oil | Why |\n| --- | --- |\n| ELF | fits |");
        match &with[0] {
            Block::Table { head, rows } => {
                assert_eq!(head.len(), 2);
                assert_eq!(rows.len(), 1);
                assert_eq!(text_of(&head[0]), "Oil");
                assert_eq!(text_of(&rows[0][1]), "fits");
            }
            other => panic!("expected a table, got {other:?}"),
        }
        let without = parse("a | b\nc | d");
        assert!(matches!(&without[0], Block::Paragraph { .. }));
    }

    #[test]
    fn a_fenced_block_keeps_its_lines_and_its_language() {
        let blocks = parse("```json\n{\"a\": 1}\n```");
        match &blocks[0] {
            Block::Code { language, text } => {
                assert_eq!(language, "json");
                assert_eq!(text, "{\"a\": 1}");
            }
            other => panic!("expected code, got {other:?}"),
        }
    }

    #[test]
    fn a_quote_keeps_its_lines() {
        let blocks = parse("> first\n> second");
        match &blocks[0] {
            Block::Quote { lines } => {
                assert_eq!(lines.len(), 2);
                assert_eq!(text_of(&lines[1]), "second");
            }
            other => panic!("expected a quote, got {other:?}"),
        }
    }

    #[test]
    fn a_rule_is_its_own_block() {
        assert!(matches!(&parse("---")[0], Block::Rule));
        // Two hyphens are not a rule, and not a list item either: a word.
        assert!(matches!(&parse("--")[0], Block::Paragraph { .. }));
    }

    #[test]
    fn every_character_of_plain_prose_survives_the_parser() {
        let source = "Buy ELF 5W-30 (RN17 / ACEA C3) at ~5.7 L; check 10,000 km & 1 year.";
        let blocks = parse(source);
        let mut rebuilt = String::new();
        for block in &blocks {
            if let Block::Paragraph { spans } = block {
                rebuilt.push_str(&text_of(spans));
            }
        }
        assert_eq!(rebuilt, source);
    }

    #[test]
    fn the_answer_the_screen_actually_receives_is_read_into_blocks() {
        // The shape the engine's agents produce: a bold lead, bullets with
        // bold terms, a table, and a trailing list of links.
        let answer = "**Engine oil**\n\n- **Capacity:** about 4.5 L\n- **Spec:** Renault RN17\n\n\
                      | Oil | Why |\n| --- | --- |\n| ELF | Renault-compatible |\n\n\
                      Sources:\n- [Auto-abc](https://www.auto-abc.eu/renault-megane/v1876O-2020/service)";
        let blocks = parse(answer);
        assert!(blocks.iter().any(|b| matches!(b, Block::List { items, .. } if items.len() == 2)));
        assert!(blocks.iter().any(|b| matches!(b, Block::Table { rows, .. } if rows.len() == 1)));
        let links: Vec<&Span> = blocks
            .iter()
            .filter_map(|b| match b {
                Block::List { items, .. } => Some(items.iter().flat_map(|i| i.spans.iter())),
                _ => None,
            })
            .flatten()
            .filter(|s| s.is_link())
            .collect();
        assert_eq!(links.len(), 1);
        assert_eq!(links[0].text, "Auto-abc");
    }
}
