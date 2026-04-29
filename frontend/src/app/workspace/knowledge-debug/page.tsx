import { ArtifactsProvider } from "@/components/workspace/artifacts";
import KnowledgeDebugPage from "@/components/workspace/knowledge-debug-page";

export default function WorkspaceKnowledgeDebugPage() {
  return (
    <ArtifactsProvider>
      <KnowledgeDebugPage />
    </ArtifactsProvider>
  );
}
