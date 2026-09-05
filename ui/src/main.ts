import { mount } from "svelte";
import App from "./App.svelte";
// Cascade order is load-bearing: structure, then a palette, then the reset,
// then the components that spend both. Themes come after tokens.css because
// they are the half of the token set that a reader gets to choose.
import "./styles/fonts.css";
import "./styles/tokens.css";
import "./styles/themes/slate.css";
import "./styles/themes/lemonade.css";
import "./styles/base.css";
import "./styles/components.css";
import "./styles/print.css";

export default mount(App, { target: document.getElementById("app")! });
