import { mount } from "svelte";
import App from "./App.svelte";
// Cascade order is load-bearing: tokens define, base resets, components use.
import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/components.css";
import "./styles/print.css";

export default mount(App, { target: document.getElementById("app")! });
