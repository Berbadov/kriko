//! Compare: drafts, slots, board, questions and the research queue, as the engine says it.

use gpui::Context;

use crate::app::Kriko;

#[derive(Default)]
pub struct State {
    pub loaded: bool,
}

impl Kriko {
    pub fn refresh_compare(&mut self, _cx: &mut Context<Self>) {}
}
