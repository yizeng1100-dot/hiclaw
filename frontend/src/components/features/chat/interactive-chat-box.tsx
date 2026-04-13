import React from "react";
import { useNavigate } from "react-router";
import { isFileImage } from "#/utils/is-file-image";
import { displayErrorToast } from "#/utils/custom-toast-handlers";
import { validateFiles } from "#/utils/file-validation";
import { CustomChatInput } from "./custom-chat-input";
import { AgentState } from "#/types/agent-state";
import { useActiveConversation } from "#/hooks/query/use-active-conversation";
import { GitControlBar } from "./git-control-bar";
import { useConversationStore } from "#/stores/conversation-store";
import { useAgentState } from "#/hooks/use-agent-state";
import { processFiles, processImages } from "#/utils/file-processing";
import { useSubConversationTaskPolling } from "#/hooks/query/use-sub-conversation-task-polling";
import { isTaskPolling } from "#/utils/utils";
// >>> CUSTOM: HiClaw <<<
import type { AgentInfo } from "#/api/custom-skill-service/agent-service.api";
import { TaskService } from "#/api/custom-skill-service/task-service.api";
import { useCreateConversation } from "#/hooks/mutation/use-create-conversation";
import { PerfReportDownload } from "#/components/features/custom/skill-management/perf-report-download";
// >>> END CUSTOM <<<

interface InteractiveChatBoxProps {
  onSubmit: (message: string, images: File[], files: File[]) => void;
}

export function InteractiveChatBox({ onSubmit }: InteractiveChatBoxProps) {
  const navigate = useNavigate();
  const {
    images,
    files,
    addImages,
    addFiles,
    clearAllFiles,
    addFileLoading,
    removeFileLoading,
    addImageLoading,
    removeImageLoading,
    subConversationTaskId,
    setShouldHideSuggestions,
  } = useConversationStore();

  const { curAgentState } = useAgentState();
  const { data: conversation } = useActiveConversation();

  // >>> CUSTOM: HiClaw — Agent selection <<<
  const [activeAgentName, setActiveAgentName] = React.useState<string | null>(
    null,
  );
  const [agentStarting, setAgentStarting] = React.useState(false);
  const [perfAgentId, setPerfAgentIdState] = React.useState<string | null>(() =>
    sessionStorage.getItem("hiclaw_perf_agent_id"),
  );
  const setPerfAgentId = (id: string | null) => {
    setPerfAgentIdState(id);
    if (id) sessionStorage.setItem("hiclaw_perf_agent_id", id);
    else sessionStorage.removeItem("hiclaw_perf_agent_id");
  };
  const { mutateAsync: createConversation } = useCreateConversation();

  const handleSelectAgent = React.useCallback(
    async (agent: AgentInfo) => {
      // Every agent goes through the same create-task + create-conv +
      // navigate flow. Perf-analysis used to have a special in-place
      // branch rendering PerfAnalysisInlinePanel inside the current
      // conv's chat box; it's been retired in favour of the skill-
      // driven DynamicFormPanel (perf-analysis-workflow.md now declares
      // its own input_form + submit_message frontmatter). This removes
      // ~200 lines of hardcoded UI and means new agents need zero
      // frontend code — just a skill .md.
      setPerfAgentId(agent.id);
      setActiveAgentName(agent.name);
      setAgentStarting(true);
      try {
        const taskResult = await TaskService.createTask({ agent_id: agent.id });
        const prompt = taskResult.agent.system_prompt
          ? `[Agent: ${taskResult.agent.name}]\n\n${taskResult.agent.system_prompt}`
          : `Execute Agent: ${taskResult.agent.name}`;

        const convData = await createConversation({ query: prompt });
        await TaskService.startTask(
          taskResult.task_id,
          convData.conversation_id,
        ).catch(() => {});
        navigate(`/conversations/${convData.conversation_id}`);
      } catch (e) {
        // eslint-disable-next-line no-console
        console.error("Failed to start agent:", e);
        displayErrorToast("Failed to start agent");
      } finally {
        setAgentStarting(false);
        setActiveAgentName(null);
      }
    },
    [navigate, createConversation, setShouldHideSuggestions],
  );

  // >>> END CUSTOM <<<

  // Poll sub-conversation task to check if it's loading
  const { taskStatus: subConversationTaskStatus } =
    useSubConversationTaskPolling(
      subConversationTaskId,
      conversation?.conversation_id || null,
    );

  // Helper function to validate and filter files
  const validateAndFilterFiles = (selectedFiles: File[]) => {
    const validation = validateFiles(selectedFiles, [...images, ...files]);

    if (!validation.isValid) {
      displayErrorToast(`Error: ${validation.errorMessage}`);
      return null;
    }

    const validFiles = selectedFiles.filter((f) => !isFileImage(f));
    const validImages = selectedFiles.filter((f) => isFileImage(f));

    return { validFiles, validImages };
  };

  // Helper function to show loading indicators for files
  const showLoadingIndicators = (validFiles: File[], validImages: File[]) => {
    validFiles.forEach((file) => addFileLoading(file.name));
    validImages.forEach((image) => addImageLoading(image.name));
  };

  // Helper function to handle successful file processing results
  const handleSuccessfulFiles = (fileResults: { successful: File[] }) => {
    if (fileResults.successful.length > 0) {
      addFiles(fileResults.successful);
      fileResults.successful.forEach((file) => removeFileLoading(file.name));
    }
  };

  // Helper function to handle successful image processing results
  const handleSuccessfulImages = (imageResults: { successful: File[] }) => {
    if (imageResults.successful.length > 0) {
      addImages(imageResults.successful);
      imageResults.successful.forEach((image) =>
        removeImageLoading(image.name),
      );
    }
  };

  // Helper function to handle failed file processing results
  const handleFailedFiles = (
    fileResults: { failed: { file: File; error: Error }[] },
    imageResults: { failed: { file: File; error: Error }[] },
  ) => {
    fileResults.failed.forEach(({ file, error }) => {
      removeFileLoading(file.name);
      displayErrorToast(
        `Failed to process file ${file.name}: ${error.message}`,
      );
    });

    imageResults.failed.forEach(({ file, error }) => {
      removeImageLoading(file.name);
      displayErrorToast(
        `Failed to process image ${file.name}: ${error.message}`,
      );
    });
  };

  // Helper function to clear loading states on error
  const clearLoadingStates = (validFiles: File[], validImages: File[]) => {
    validFiles.forEach((file) => removeFileLoading(file.name));
    validImages.forEach((image) => removeImageLoading(image.name));
  };

  const handleUpload = async (selectedFiles: File[]) => {
    // Step 1: Validate and filter files
    const result = validateAndFilterFiles(selectedFiles);
    if (!result) return;

    const { validFiles, validImages } = result;

    // Step 2: Show loading indicators immediately
    showLoadingIndicators(validFiles, validImages);

    // Step 3: Process files using REAL FileReader
    try {
      const [fileResults, imageResults] = await Promise.all([
        processFiles(validFiles),
        processImages(validImages),
      ]);

      // Step 4: Handle successful results
      handleSuccessfulFiles(fileResults);
      handleSuccessfulImages(imageResults);

      // Step 5: Handle failed results
      handleFailedFiles(fileResults, imageResults);
    } catch {
      // Clear loading states and show error
      clearLoadingStates(validFiles, validImages);
      displayErrorToast("An unexpected error occurred while processing files");
    }
  };

  const handleSubmit = (message: string) => {
    onSubmit(message, images, files);
    clearAllFiles();
  };

  const handleSuggestionsClick = (suggestion: string) => {
    handleSubmit(suggestion);
  };

  // Allow users to submit messages during LOADING state - they will be
  // queued server-side and delivered when the conversation becomes ready
  const isDisabled =
    curAgentState === AgentState.AWAITING_USER_CONFIRMATION ||
    isTaskPolling(subConversationTaskStatus) ||
    agentStarting;

  return (
    <div data-testid="interactive-chat-box">
      {/* >>> CUSTOM: HiClaw — Phase progress moved to right-side tab (phase-progress-tab.tsx) <<< */}
      {/* >>> END CUSTOM <<< */}
      {/* >>> CUSTOM: HiClaw — Agent report download (only after agent finishes) <<< */}
      {(curAgentState === AgentState.STOPPED ||
        curAgentState === AgentState.FINISHED) &&
        conversation?.conversation_id && (
          <PerfReportDownload
            conversationId={conversation.conversation_id}
            agentId={perfAgentId}
          />
        )}
      {/* >>> END CUSTOM <<< */}
      {/* HiClaw: perf analysis inline panel retired — perf agent now
          uses the shared DynamicFormPanel driven by
          perf-analysis-workflow.md's input_form frontmatter. */}
      {/* >>> CUSTOM: HiClaw — Agent starting indicator <<< */}
      {activeAgentName && (
        <div className="mb-2 px-3 py-1.5 bg-[#4ECDC4]/10 border border-[#4ECDC4]/30 rounded-lg">
          <span className="text-xs text-[#4ECDC4]">
            {`${activeAgentName} 启动中...`}
          </span>
        </div>
      )}
      {/* >>> END CUSTOM <<< */}
      <CustomChatInput
        disabled={isDisabled}
        onSubmit={handleSubmit}
        onFilesPaste={handleUpload}
        conversationStatus={conversation?.status || null}
        // >>> CUSTOM: HiClaw <<<
        onSelectAgent={handleSelectAgent}
        // >>> END CUSTOM <<<
      />
      <div className="mt-4">
        <GitControlBar onSuggestionsClick={handleSuggestionsClick} />
      </div>
    </div>
  );
}
