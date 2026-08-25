import { AppShell } from "./components/app-shell";
import { ConversationWorkspace } from "./components/conversation-workspace";

export default function HomePage() {
  return (
    <AppShell>
      <ConversationWorkspace />
    </AppShell>
  );
}
