import { openHands } from "#/api/open-hands-axios";

export interface AgentInfo {
  id: string;
  name: string;
  description: string | null;
  category: string | null;
  tags: string[];
  config_json: string | null;
  is_enabled: boolean;
  usage_count: number;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface SkillBrief {
  id: string;
  name: string;
  description: string | null;
}

export interface AgentDetail extends AgentInfo {
  system_prompt: string | null;
  default_llm_model: string | null;
  config_json: string | null;
  usage_instructions: string | null;
  skill_ids: string[];
  skills: SkillBrief[];
  is_favorited: boolean;
}

export interface AgentListResponse {
  agents: AgentInfo[];
  total: number;
}

export interface AgentCreateData {
  name: string;
  description?: string;
  system_prompt?: string;
  category?: string;
  tags?: string[];
  default_llm_model?: string;
  skill_ids?: string[];
}

export class AgentService {
  static async listAgents(params?: {
    search?: string;
    category?: string;
    tag?: string;
    is_enabled?: boolean;
    sort_by?: string;
    sort_order?: string;
    limit?: number;
    offset?: number;
  }): Promise<AgentListResponse> {
    const resp = await openHands.get("/api/v1/agents", { params });
    return resp.data;
  }

  static async getAgent(agentId: string): Promise<AgentDetail> {
    const resp = await openHands.get(`/api/v1/agents/${agentId}`);
    return resp.data;
  }

  static async createAgent(data: AgentCreateData): Promise<{ id: string }> {
    const resp = await openHands.post("/api/v1/agents", data);
    return resp.data;
  }

  static async updateAgent(
    agentId: string,
    data: Partial<AgentCreateData & { is_enabled: boolean }>,
  ): Promise<void> {
    await openHands.patch(`/api/v1/agents/${agentId}`, data);
  }

  static async deleteAgent(agentId: string): Promise<void> {
    await openHands.delete(`/api/v1/agents/${agentId}`);
  }

  static async setAgentSkills(
    agentId: string,
    skillIds: string[],
  ): Promise<void> {
    await openHands.put(`/api/v1/agents/${agentId}/skills`, skillIds);
  }

  static async toggleFavorite(
    agentId: string,
  ): Promise<{ is_favorited: boolean }> {
    const resp = await openHands.post(`/api/v1/agents/${agentId}/favorite`);
    return resp.data;
  }

  static async listFavorites(): Promise<AgentListResponse> {
    const resp = await openHands.get("/api/v1/agents/favorites");
    return resp.data;
  }

  static async getCategories(): Promise<string[]> {
    const resp = await openHands.get("/api/v1/agents/categories");
    return resp.data;
  }

  static async getCreators(): Promise<string[]> {
    const resp = await openHands.get("/api/v1/agents/creators");
    return resp.data;
  }

  static async importFromGit(data: {
    git_url: string;
    branch?: string;
    subdir?: string;
    token?: string;
    agent_name?: string;
    agent_description?: string;
    agent_category?: string;
  }): Promise<{
    status: string;
    agent_id: string;
    agent_name: string;
    skill_count: number;
    workflow_name: string | null;
  }> {
    const resp = await openHands.post("/api/v1/agents/import-from-git", data);
    return resp.data;
  }

  static async importFromFiles(
    files: File[],
    opts?: {
      agent_name?: string;
      agent_description?: string;
      agent_category?: string;
    },
  ): Promise<{
    status: string;
    agent_id: string;
    agent_name: string;
    skill_count: number;
    workflow_name: string | null;
  }> {
    const formData = new FormData();
    for (const f of files) {
      formData.append("files", f);
    }
    const params = new URLSearchParams();
    if (opts?.agent_name) params.set("agent_name", opts.agent_name);
    if (opts?.agent_description)
      params.set("agent_description", opts.agent_description);
    if (opts?.agent_category) params.set("agent_category", opts.agent_category);
    const url = `/api/v1/agents/import-from-files${params.toString() ? `?${params}` : ""}`;
    const resp = await openHands.post(url, formData, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    return resp.data;
  }

  static async syncAgent(agentId: string): Promise<{
    status: string;
    skill_count: number;
    workflow_name: string | null;
  }> {
    const resp = await openHands.post(`/api/v1/agents/${agentId}/sync`);
    return resp.data;
  }
}
