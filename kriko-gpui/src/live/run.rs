//! Run, the dock and Agents: jobs, their feed and the agents on this machine, as the engine says it.

use gpui::Context;

use crate::app::Kriko;

#[derive(Default)]
pub struct State {
    pub loaded: bool,
}

impl Kriko {
    pub fn refresh_run(&mut self, _cx: &mut Context<Self>) {}
}
