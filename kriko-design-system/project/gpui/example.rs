mod theme;

use gpui::{div, px, rgb, rgba, App, AppContext, Application, Context, IntoElement, ParentElement, Render, Styled, Window, WindowOptions};
use theme::*;

struct Home;

impl Render for Home {
    fn render(&mut self, _w: &mut Window, _cx: &mut Context<Self>) -> impl IntoElement {
        div()
            .size_full()
            .flex()
            .bg(rgb(GROUND))
            .text_color(rgb(INK))
            .child(
                div().w(px(248.0)).h_full().bg(rgb(SURFACE_1)).flex().flex_col().p(px(12.0)).gap(px(2.0))
                    .child(nav_item("home", "Home", true))
                    .child(nav_item("run", "Run", false)),
            )
            .child(
                div().flex_1().flex().flex_col()
                    .child(hero("assets/sky-hero.png", 360.0).child(frost().child(key("start", "Start check"))))
                    .child(div().p(px(40.0)).flex().gap(px(24.0))
                        .child(card().child(meter(76.0, 24)))
                        .child(card().child(tag(TagState::Need, "Needs you")))
                        .child(card().child(switch("sw", true)))
                        .child(card().child(plate("p", "Rescan")))
                        .child(card().child(agent_tile(&["#####", "#...#", "#####", "#...#", "#...#"], None)))
                        .bg(rgba(GLASS_1))),
            )
    }
}

fn main() {
    Application::new().run(|cx: &mut App| {
        cx.open_window(WindowOptions::default(), |_, cx| cx.new(|_| Home)).unwrap();
    });
}
