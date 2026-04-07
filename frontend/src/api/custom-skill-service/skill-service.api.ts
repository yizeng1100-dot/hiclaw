// >>> CUSTOM: HiClaw — Skill service backed by Git repo API <<<
import { openHands } from "#/api/open-hands-axios";

export interface SkillInfo {
  id: string;
  name: string;
  description: string | null;
  category: string | null;
  skill_type: string;
  triggers: string[];
  tags: string[];
  is_global: boolean;
  is_active: boolean;
  created_by: string | null;
  current_version: number;
  created_at: string;
  updated_at: string;
}

export interface SkillVersionInfo {
  id: string;
  skill_id: string;
  version: number;
  content: string;
  changelog: string | null;
  performance_notes: string | null;
  is_current: boolean;
  created_by: string | null;
  created_at: string;
}

export interface ScriptInfo {
  id: string;
  skill_id: string;
  filename: string;
  language: string | null;
  content: string;
  description: string | null;
  created_at: string;
  updated_at: string;
}

export interface SkillDetail extends SkillInfo {
  content: string;
  versions: SkillVersionInfo[];
  scripts: ScriptInfo[];
}

export interface SkillListResponse {
  results: SkillInfo[];
  total: number;
}

interface GitSkillInfo {
  path: string;
  name: string;
  description: string;
  category: string;
  content: string;
  triggers: string[];
}

interface GitCommit {
  hash: string;
  author: string;
  email: string;
  date: string;
  message: string;
}

function toSkillInfo(git: GitSkillInfo): SkillInfo {
  return {
    id: git.path,
    name: git.name,
    description: git.description || null,
    category: git.category || null,
    skill_type: "knowledge",
    triggers: git.triggers || [],
    tags: [],
    is_global: git.category === "global",
    is_active: true,
    created_by: null,
    current_version: 1,
    created_at: "",
    updated_at: "",
  };
}

function toSkillDetail(git: GitSkillInfo, history: GitCommit[] = []): SkillDetail {
  return {
    ...toSkillInfo(git),
    content: git.content,
    versions: history.map((c, i) => ({
      id: c.hash,
      skill_id: git.path,
      version: history.length - i,
      content: "",
      changelog: c.message,
      performance_notes: null,
      is_current: i === 0,
      created_by: c.author,
      created_at: c.date,
    })),
    scripts: [],
  };
}

class SkillService {
  static async listSkills(params?: {
    search?: string;
    category?: string;
    tag?: string;
    is_active?: boolean;
    limit?: number;
    offset?: number;
  }): Promise<SkillListResponse> {
    const { data } = await openHands.get<GitSkillInfo[]>("/api/hiclaw/skills", {
      params: { search: params?.search, category: params?.category },
    });
    const results = data.map(toSkillInfo);
    return { results, total: results.length };
  }

  static async getSkill(skillId: string): Promise<SkillDetail> {
    const { data: skill } = await openHands.get<GitSkillInfo>(
      `/api/hiclaw/skills/${skillId}`,
    );
    let history: GitCommit[] = [];
    try {
      const { data } = await openHands.get<GitCommit[]>(
        `/api/hiclaw/skills-history/${skillId}`,
      );
      history = data;
    } catch { /* no history */ }
    return toSkillDetail(skill, history);
  }

  static async createSkill(skill: {
    name: string;
    description?: string;
    category?: string;
    triggers?: string[];
    tags?: string[];
    content: string;
  }): Promise<SkillDetail> {
    const category = skill.category || "global";
    const path = `${category}/${skill.name.replace(/\s+/g, "-").toLowerCase()}.md`;

    const frontmatter = [
      "---",
      `name: ${skill.name}`,
      skill.description ? `description: ${skill.description}` : "",
      skill.triggers?.length
        ? `trigger:\n  type: keyword\n  keywords: [${skill.triggers.map((t) => `"${t}"`).join(", ")}]`
        : "",
      "---",
      "",
    ].filter(Boolean).join("\n");

    await openHands.post("/api/hiclaw/skills", { path, content: frontmatter + skill.content });
    return this.getSkill(path);
  }

  static async updateSkill(
    skillId: string,
    updates: {
      description?: string;
      category?: string;
      triggers?: string[];
      tags?: string[];
      is_global?: boolean;
      is_active?: boolean;
    },
  ): Promise<SkillDetail> {
    const current = await this.getSkill(skillId);
    if (updates.description !== undefined || updates.triggers !== undefined) {
      let content = current.content;
      if (updates.description !== undefined) {
        content = content.replace(/description:.*$/m, `description: ${updates.description}`);
      }
      await openHands.put(`/api/hiclaw/skills/${skillId}`, {
        content,
        message: `Update metadata: ${skillId}`,
      });
    }
    return this.getSkill(skillId);
  }

  static async deleteSkill(skillId: string): Promise<void> {
    await openHands.delete(`/api/hiclaw/skills/${skillId}`);
  }

  static async uploadSkillFiles(formData: FormData): Promise<SkillDetail> {
    const name = formData.get("name") as string;
    const description = (formData.get("description") as string) || "";
    const category = (formData.get("category") as string) || "global";
    const file = formData.get("files") as File;
    let content = "";
    if (file) {
      content = await file.text();
    }
    return this.createSkill({ name, description, category, content });
  }

  static async createVersion(
    skillId: string,
    version: { content: string; changelog?: string; performance_notes?: string },
  ): Promise<SkillVersionInfo> {
    await openHands.put(`/api/hiclaw/skills/${skillId}`, {
      content: version.content,
      message: version.changelog || `Update skill: ${skillId}`,
    });
    const detail = await this.getSkill(skillId);
    return detail.versions[0] || {
      id: "", skill_id: skillId, version: 1, content: version.content,
      changelog: version.changelog || null, performance_notes: null,
      is_current: true, created_by: null, created_at: new Date().toISOString(),
    };
  }

  static async rollbackVersion(skillId: string, _versionId: string): Promise<SkillDetail> {
    return this.getSkill(skillId);
  }

  static async uploadScript(_skillId: string, _formData: FormData): Promise<ScriptInfo> {
    throw new Error("Scripts are managed via Git");
  }

  static async deleteScript(_scriptId: string): Promise<void> {
    throw new Error("Scripts are managed via Git");
  }

  static async getCategories(): Promise<string[]> {
    const { data } = await openHands.get<string[]>("/api/hiclaw/skills-categories");
    return data;
  }
}

export default SkillService;
// >>> END CUSTOM <<<
