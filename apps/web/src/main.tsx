import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { Live } from "./Live";
import { pageMode } from "./liveApi";
import { RepPage } from "./RepPage";
import "./styles.css";

const root = document.getElementById("root");
if (!root) throw new Error("#root is missing from index.html");
const mode = pageMode(location.search);
createRoot(root).render(
  <StrictMode>
    {mode.kind === "live" ? <Live runId={mode.id} /> : mode.kind === "rep" ? <RepPage caseId={mode.id} /> : <App />}
  </StrictMode>,
);
