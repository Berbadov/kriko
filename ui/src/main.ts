import { mount } from "svelte";
import App from "./App.svelte";
// Cascade order is load-bearing: structure, then the palette, then the reset,
// then the components that spend both. The palette comes after tokens.css
// because the components' colour aliases are answered there.
import "./styles/fonts.css";
import "./styles/tokens.css";
import "./styles/themes/panel.css";
import "./styles/base.css";
import "./styles/components.css";
import "./styles/motion.css";
import "./styles/print.css";

export default mount(App, { target: document.getElementById("app")! });
