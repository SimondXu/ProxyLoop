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
import { ThemeContext } from "./shell/ThemeToggle";
import { StartPage } from "./StartPage";
import { themeController } from "./theme";

const root = document.getElementById("root");
if (!root) throw new Error("#root is missing from index.html");
const mode = pageMode(location.search);
// One theme controller for the page's life (index.html set the first theme): it follows the OS while on "system".
const theme = themeController({
  store: () => window.localStorage,
  media: window.matchMedia("(prefers-color-scheme: dark)"),
  setTheme: (t) => document.documentElement.setAttribute("data-theme", t),
});
createRoot(root).render(
  <StrictMode>
    <ThemeContext value={theme}>
      {mode.kind === "live" ? (
        <Live runId={mode.id} />
      ) : mode.kind === "rep" ? (
        <RepPage caseId={mode.id} />
      ) : mode.kind === "start" ? (
        <StartPage />
      ) : (
        <App />
      )}
    </ThemeContext>
  </StrictMode>,
);
