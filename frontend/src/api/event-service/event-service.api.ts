import axios from "axios";
import { buildHttpBaseUrl } from "#/utils/websocket-url";
import { buildSessionHeaders } from "#/utils/utils";
import type {
  ConfirmationResponseRequest,
  ConfirmationResponseResponse,
} from "./event-service.types";
import { openHands } from "../open-hands-axios";
import { OpenHandsEvent } from "#/types/v1/core";

class EventService {
  /**
   * Respond to a confirmation request in a V1 conversation
   * @param conversationId The conversation ID
   * @param conversationUrl The conversation URL (e.g., "http://localhost:54928/api/conversations/...")
   * @param request The confirmation response request
   * @param sessionApiKey Session API key for authentication (required for V1)
   * @returns The confirmation response
   */
  static async respondToConfirmation(
    conversationId: string,
    conversationUrl: string,
    request: ConfirmationResponseRequest,
    sessionApiKey?: string | null,
  ): Promise<ConfirmationResponseResponse> {
    // Build the runtime URL using the conversation URL
    const runtimeUrl = buildHttpBaseUrl(conversationUrl);

    // Build session headers for authentication
    const headers = buildSessionHeaders(sessionApiKey);

    // Make the API call to the runtime endpoint
    const { data } = await axios.post<ConfirmationResponseResponse>(
      `${runtimeUrl}/api/conversations/${conversationId}/events/respond_to_confirmation`,
      request,
      { headers },
    );

    return data;
  }

  /**
   * Get event count for a V1 conversation
   * @param conversationId The conversation ID
   * @param conversationUrl The conversation URL (kept for API compatibility, ignored)
   * @param sessionApiKey Session API key (kept for API compatibility, ignored)
   * @returns The event count
   *
   * >>> CUSTOM: HiClaw <<<
   * Read from app-server's local event store instead of the sandbox tunnel.
   * This way, stopped/restarted conversations can still load history without
   * needing the SSH tunnel to be alive.
   */
  static async getEventCount(
    conversationId: string,
    _conversationUrl: string,
    _sessionApiKey?: string | null,
  ): Promise<number> {
    const { data } = await openHands.get<number>(
      `/api/v1/conversation/${conversationId}/events/count`,
    );
    return data;
  }

  // V1 conversations — App Server REST endpoint
  // >>> CUSTOM: HiClaw — paginate to load full history (was limited to 100) <<<
  static async searchEventsV1(conversationId: string, limit = 100) {
    const all: OpenHandsEvent[] = [];
    let pageId: string | null = null;
    // Cap pages to avoid runaway loops
    for (let i = 0; i < 100; i += 1) {
      const params: Record<string, string | number> = { limit };
      if (pageId) params.page_id = pageId;
      const { data } = await openHands.get<{
        items: OpenHandsEvent[];
        next_page_id?: string | null;
      }>(`/api/v1/conversation/${conversationId}/events/search`, { params });
      if (Array.isArray(data.items)) all.push(...data.items);
      if (!data.next_page_id) break;
      pageId = data.next_page_id;
    }
    return all;
  }
  // >>> END CUSTOM <<<

  // V0 conversations — Legacy REST endpoint
  static async searchEventsV0(conversationId: string, limit = 100) {
    const { data } = await openHands.get<{
      events: OpenHandsEvent[];
    }>(`/api/conversations/${conversationId}/events`, {
      params: { limit },
    });

    return data.events;
  }
}
export default EventService;
