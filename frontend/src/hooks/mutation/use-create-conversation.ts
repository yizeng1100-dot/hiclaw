import { useMutation, useQueryClient } from "@tanstack/react-query";
import ConversationService from "#/api/conversation-service/conversation-service.api";
import V1ConversationService from "#/api/conversation-service/v1-conversation-service.api";
import { SuggestedTask } from "#/utils/types";
import { Provider } from "#/types/settings";
import { CreateMicroagent, Conversation } from "#/api/open-hands.types";
import { useTracking } from "#/hooks/use-tracking";
import { useSettings } from "#/hooks/query/use-settings";
// >>> CUSTOM: HiClaw <<<
import { useRemoteWorkerStore } from "#/stores/remote-worker-store";
// >>> END CUSTOM <<<

interface CreateConversationVariables {
  query?: string;
  repository?: {
    name: string;
    gitProvider: Provider;
    branch?: string;
  };
  suggestedTask?: SuggestedTask;
  conversationInstructions?: string;
  createMicroagent?: CreateMicroagent;
  parentConversationId?: string;
  agentType?: "default" | "plan";
}

// Response type that combines both V1 and legacy responses
interface CreateConversationResponse extends Partial<Conversation> {
  conversation_id: string;
  session_api_key: string | null;
  url: string | null;
  // V1 specific fields
  v1_task_id?: string;
  is_v1?: boolean;
}

export const useCreateConversation = () => {
  const queryClient = useQueryClient();
  const { trackConversationCreated } = useTracking();
  const { data: settings } = useSettings();
  // >>> CUSTOM: HiClaw <<<
  const remoteEnabled = useRemoteWorkerStore((s) => s.enabled);
  const proxyUrl = useRemoteWorkerStore((s) => s.proxyUrl);
  // >>> END CUSTOM <<<

  return useMutation({
    mutationKey: ["create-conversation"],
    mutationFn: async (
      variables: CreateConversationVariables,
    ): Promise<CreateConversationResponse> => {
      const {
        query,
        repository,
        suggestedTask,
        conversationInstructions,
        createMicroagent,
        parentConversationId,
        agentType,
      } = variables;

      // >>> CUSTOM: HiClaw — use proxyUrl from store (machine already provisioned) <<<
      const remoteAgentUrl = remoteEnabled && proxyUrl ? proxyUrl : undefined;
      // >>> END CUSTOM <<<

      const useV1 = !!settings?.v1_enabled && !createMicroagent;

      if (useV1) {
        const startTask = await V1ConversationService.createConversation(
          repository?.name,
          repository?.gitProvider,
          query,
          repository?.branch,
          conversationInstructions,
          suggestedTask,
          undefined,
          parentConversationId,
          agentType,
          // >>> CUSTOM: HiClaw <<<
          remoteAgentUrl,
          // >>> END CUSTOM <<<
        );

        return {
          conversation_id: `task-${startTask.id}`,
          session_api_key: null,
          url: startTask.agent_server_url,
          v1_task_id: startTask.id,
          is_v1: true,
        };
      }

      // Use legacy API
      const conversation = await ConversationService.createConversation(
        repository?.name,
        repository?.gitProvider,
        query,
        suggestedTask,
        repository?.branch,
        conversationInstructions,
        createMicroagent,
      );

      return {
        ...conversation,
        is_v1: false,
      };
    },
    onSuccess: async (_, { repository }) => {
      trackConversationCreated({
        hasRepository: !!repository,
      });

      queryClient.removeQueries({
        queryKey: ["user", "conversations"],
      });
    },
  });
};
