// The layer order (base.css) first, then the tokens and fonts; the pages' own sheets follow.
import "./ui/base.css";
import "./ui/tokens.css";
import "./ui/fonts.css";
import "./styles.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { Live } from "./Live";
import { pageMode } from "./liveApi";
import { RepPage } from "./RepPage";
import { StartPage } from "./StartPage";

const root = document.getElementById("root");
if (!root) throw new Error("#root is missing from index.html");
const mode = pageMode(location.search);
createRoot(root).render(
  <StrictMode>
    {mode.kind === "live" ? (
      <Live runId={mode.id} />
    ) : mode.kind === "rep" ? (
      <RepPage caseId={mode.id} />
    ) : mode.kind === "start" ? (
      <StartPage />
    ) : (
      <App />
    )}
  </StrictMode>,
);
