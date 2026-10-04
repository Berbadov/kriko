//! History, Home, Browse and Activity, as the engine says it.

use gpui::Context;

use crate::app::Kriko;

#[derive(Default)]
pub struct State {
    pub loaded: bool,
}

impl Kriko {
    pub fn refresh_history(&mut self, _cx: &mut Context<Self>) {}
}
