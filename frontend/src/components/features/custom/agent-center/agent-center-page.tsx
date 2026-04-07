/* eslint-disable i18next/no-literal-string, no-nested-ternary, no-console, jsx-a11y/label-has-associated-control */
import React from "react";
import {
  AgentService,
  type AgentInfo,
} from "#/api/custom-skill-service/agent-service.api";
import { AgentCard } from "./agent-card";
import { cn } from "#/utils/utils";

const PAGE_SIZE = 12;
const SEARCH_HISTORY_KEY = "hiclaw_agent_search_history";
const MAX_HISTORY = 8;

const SORT_OPTIONS = [
  { value: "created_at:desc", label: "最新创建" },
  { value: "created_at:asc", label: "最早创建" },
  { value: "usage_count:desc", label: "使用最多" },
  { value: "name:asc", label: "名称 A-Z" },
  { value: "name:desc", label: "名称 Z-A" },
];

function loadSearchHistory(): string[] {
  try {
    return JSON.parse(localStorage.getItem(SEARCH_HISTORY_KEY) || "[]");
  } catch {
    return [];
  }
}

function saveSearchHistory(history: string[]) {
  localStorage.setItem(
    SEARCH_HISTORY_KEY,
    JSON.stringify(history.slice(0, MAX_HISTORY)),
  );
}

export function AgentCenterPage() {
  const [agents, setAgents] = React.useState<AgentInfo[]>([]);
  const [total, setTotal] = React.useState(0);
  const [loading, setLoading] = React.useState(true);

  // Search
  const [searchInput, setSearchInput] = React.useState("");
  const [search, setSearch] = React.useState("");
  const [searchHistory, setSearchHistory] =
    React.useState<string[]>(loadSearchHistory);
  const [showHistory, setShowHistory] = React.useState(false);
  const searchRef = React.useRef<HTMLDivElement>(null);

  // Filters
  const [category, setCategory] = React.useState("");
  const [tag, setTag] = React.useState("");
  const [createdBy, setCreatedBy] = React.useState("");
  const [categories, setCategories] = React.useState<string[]>([]);
  const [creators, setCreators] = React.useState<string[]>([]);
  const [allTags, setAllTags] = React.useState<string[]>([]);

  // Sort & Pagination
  const [sortKey, setSortKey] = React.useState("created_at:desc");
  const [page, setPage] = React.useState(0);

  // Favorites
  const [favorites, setFavorites] = React.useState<Set<string>>(new Set());

  // Create modal
  const [showCreateModal, setShowCreateModal] = React.useState(false);
  const [newName, setNewName] = React.useState("");
  const [newDesc, setNewDesc] = React.useState("");
  const [newCategory, setNewCategory] = React.useState("");
  const [newPrompt, setNewPrompt] = React.useState("");
  const [newTags, setNewTags] = React.useState("");
  const [creating, setCreating] = React.useState(false);

  // Git import modal
  const [showImportModal, setShowImportModal] = React.useState(false);
  const [gitUrl, setGitUrl] = React.useState("");
  const [gitBranch, setGitBranch] = React.useState("main");
  const [gitSubdir, setGitSubdir] = React.useState("");
  const [gitToken, setGitToken] = React.useState("");
  const [gitAgentName, setGitAgentName] = React.useState("");
  const [gitAgentDesc, setGitAgentDesc] = React.useState("");
  const [gitAgentCategory, setGitAgentCategory] = React.useState("");
  const [importing, setImporting] = React.useState(false);
  const [importResult, setImportResult] = React.useState<{
    agent_name: string;
    skill_count: number;
    workflow_name: string | null;
  } | null>(null);

  // Close search history dropdown on outside click
  React.useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (searchRef.current && !searchRef.current.contains(e.target as Node)) {
        setShowHistory(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  // Fetch agents
  const fetchAgents = React.useCallback(async () => {
    setLoading(true);
    try {
      const [sortBy, sortOrder] = sortKey.split(":");
      const params: Record<string, string | number | boolean> = {
        sort_by: sortBy,
        sort_order: sortOrder,
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      };
      if (search) params.search = search;
      if (category) params.category = category;
      if (tag) params.tag = tag;
      if (createdBy) params.created_by = createdBy;
      const data = await AgentService.listAgents(params);
      setAgents(data.agents);
      setTotal(data.total);
    } catch (e) {
      console.error("Failed to load agents:", e);
    } finally {
      setLoading(false);
    }
  }, [search, category, tag, createdBy, sortKey, page]);

  React.useEffect(() => {
    fetchAgents();
  }, [fetchAgents]);

  // Load filter options
  React.useEffect(() => {
    AgentService.getCategories()
      .then(setCategories)
      .catch(() => {});
    AgentService.getCreators()
      .then(setCreators)
      .catch(() => {});
    AgentService.listFavorites()
      .then((data) => setFavorites(new Set(data.agents.map((a) => a.id))))
      .catch(() => {});
    // Collect unique tags from all agents
    AgentService.listAgents({ limit: 200 })
      .then((data) => {
        const tags = new Set<string>();
        data.agents.forEach((a) => a.tags.forEach((t) => tags.add(t)));
        setAllTags(Array.from(tags).sort());
      })
      .catch(() => {});
  }, []);

  // Search handlers
  const handleSearch = () => {
    const trimmed = searchInput.trim();
    setSearch(trimmed);
    setPage(0);
    if (trimmed) {
      const updated = [
        trimmed,
        ...searchHistory.filter((h) => h !== trimmed),
      ].slice(0, MAX_HISTORY);
      setSearchHistory(updated);
      saveSearchHistory(updated);
    }
    setShowHistory(false);
  };

  const handleSearchKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") handleSearch();
  };

  const handlePickHistory = (term: string) => {
    setSearchInput(term);
    setSearch(term);
    setPage(0);
    setShowHistory(false);
  };

  const handleClearHistory = () => {
    setSearchHistory([]);
    saveSearchHistory([]);
  };

  // Favorites
  const handleToggleFavorite = async (agentId: string) => {
    try {
      const result = await AgentService.toggleFavorite(agentId);
      setFavorites((prev) => {
        const next = new Set(prev);
        if (result.is_favorited) next.add(agentId);
        else next.delete(agentId);
        return next;
      });
    } catch (e) {
      console.error("Failed to toggle favorite:", e);
    }
  };

  // Create
  const handleCreate = async () => {
    if (!newName.trim()) return;
    setCreating(true);
    try {
      const tags = newTags
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean);
      await AgentService.createAgent({
        name: newName,
        description: newDesc || undefined,
        system_prompt: newPrompt || undefined,
        category: newCategory || undefined,
        tags,
      });
      setShowCreateModal(false);
      setNewName("");
      setNewDesc("");
      setNewCategory("");
      setNewPrompt("");
      setNewTags("");
      fetchAgents();
    } catch (e) {
      console.error("Failed to create agent:", e);
    } finally {
      setCreating(false);
    }
  };

  // Git import
  const handleImport = async () => {
    if (!gitUrl.trim()) return;
    setImporting(true);
    setImportResult(null);
    try {
      const result = await AgentService.importFromGit({
        git_url: gitUrl,
        branch: gitBranch || "main",
        subdir: gitSubdir || undefined,
        token: gitToken || undefined,
        agent_name: gitAgentName || undefined,
        agent_description: gitAgentDesc || undefined,
        agent_category: gitAgentCategory || undefined,
      });
      setImportResult({
        agent_name: result.agent_name,
        skill_count: result.skill_count,
        workflow_name: result.workflow_name,
      });
      fetchAgents();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "导入失败";
      setImportResult({ agent_name: "", skill_count: 0, workflow_name: msg });
    } finally {
      setImporting(false);
    }
  };

  const closeImportModal = () => {
    setShowImportModal(false);
    setGitUrl("");
    setGitBranch("main");
    setGitSubdir("");
    setGitToken("");
    setGitAgentName("");
    setGitAgentDesc("");
    setGitAgentCategory("");
    setImportResult(null);
  };

  const totalPages = Math.ceil(total / PAGE_SIZE);

  return (
    <div className="h-full flex flex-col p-6 text-white overflow-auto custom-scrollbar">
      {/* Header */}
      <div className="flex items-center justify-between mb-5">
        <div>
          <h1 className="text-2xl font-bold">Agent 中心</h1>
          <p className="text-sm text-gray-400 mt-1">共 {total} 个 Agent</p>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => setShowImportModal(true)}
            className="px-4 py-2 bg-[#21262d] hover:bg-[#30363d] border border-[#30363d] rounded-lg text-sm font-medium transition"
          >
            从 Git 导入
          </button>
          <button
            type="button"
            onClick={() => setShowCreateModal(true)}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg text-sm font-medium transition"
          >
            + 创建 Agent
          </button>
        </div>
      </div>

      {/* Search with history */}
      <div className="flex gap-3 mb-4">
        <div className="flex-1 relative" ref={searchRef}>
          <div className="flex">
            <input
              type="text"
              placeholder="搜索 Agent 名称或描述..."
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              onFocus={() => searchHistory.length > 0 && setShowHistory(true)}
              onKeyDown={handleSearchKeyDown}
              className="flex-1 px-3 py-2 bg-[#0d1117] border border-[#30363d] rounded-l-lg text-sm text-white placeholder:text-gray-500 focus:outline-none focus:border-blue-500"
            />
            <button
              type="button"
              onClick={handleSearch}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-r-lg text-sm transition"
            >
              搜索
            </button>
          </div>
          {/* Search history dropdown */}
          {showHistory && searchHistory.length > 0 && (
            <div className="absolute top-full left-0 right-0 mt-1 bg-[#161b22] border border-[#30363d] rounded-lg z-10 shadow-lg">
              <div className="flex items-center justify-between px-3 py-1.5 border-b border-[#30363d]">
                <span className="text-xs text-gray-500">搜索历史</span>
                <button
                  type="button"
                  onClick={handleClearHistory}
                  className="text-xs text-gray-500 hover:text-red-400"
                >
                  清除
                </button>
              </div>
              {searchHistory.map((term) => (
                <button
                  key={term}
                  type="button"
                  onClick={() => handlePickHistory(term)}
                  className="w-full text-left px-3 py-1.5 text-sm text-gray-300 hover:bg-[#21262d] transition"
                >
                  {term}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Filters & Sort */}
      <div className="flex flex-wrap gap-3 mb-5">
        <select
          value={category}
          onChange={(e) => {
            setCategory(e.target.value);
            setPage(0);
          }}
          className="px-3 py-1.5 bg-[#0d1117] border border-[#30363d] rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
        >
          <option value="">全部分类</option>
          {categories.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
        <select
          value={tag}
          onChange={(e) => {
            setTag(e.target.value);
            setPage(0);
          }}
          className="px-3 py-1.5 bg-[#0d1117] border border-[#30363d] rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
        >
          <option value="">全部标签</option>
          {allTags.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        <select
          value={createdBy}
          onChange={(e) => {
            setCreatedBy(e.target.value);
            setPage(0);
          }}
          className="px-3 py-1.5 bg-[#0d1117] border border-[#30363d] rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
        >
          <option value="">全部创建者</option>
          {creators.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
        <select
          value={sortKey}
          onChange={(e) => {
            setSortKey(e.target.value);
            setPage(0);
          }}
          className="px-3 py-1.5 bg-[#0d1117] border border-[#30363d] rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
        >
          {SORT_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
        {(search || category || tag || createdBy) && (
          <button
            type="button"
            onClick={() => {
              setSearch("");
              setSearchInput("");
              setCategory("");
              setTag("");
              setCreatedBy("");
              setPage(0);
            }}
            className="px-3 py-1.5 text-sm text-gray-400 hover:text-white transition"
          >
            清除筛选
          </button>
        )}
      </div>

      {/* Agent Grid */}
      {loading ? (
        <div className="flex-1 flex items-center justify-center">
          <p className="text-gray-500">加载中...</p>
        </div>
      ) : agents.length === 0 ? (
        <div className="flex-1 flex flex-col items-center justify-center">
          <p className="text-gray-500 mb-2">暂无 Agent</p>
          <p className="text-gray-600 text-sm">
            点击&ldquo;创建 Agent&rdquo;开始配置你的第一个 Agent
          </p>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {agents.map((agent) => (
              <AgentCard
                key={agent.id}
                agent={agent}
                searchTerm={search}
                isFavorited={favorites.has(agent.id)}
                onToggleFavorite={handleToggleFavorite}
              />
            ))}
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-center gap-2 mt-6">
              <button
                type="button"
                onClick={() => setPage((p) => Math.max(0, p - 1))}
                disabled={page === 0}
                className="px-3 py-1.5 text-sm rounded bg-[#21262d] text-gray-300 hover:bg-[#30363d] disabled:opacity-40 transition"
              >
                上一页
              </button>
              {Array.from({ length: totalPages }, (_, i) => (
                <button
                  key={i}
                  type="button"
                  onClick={() => setPage(i)}
                  className={cn(
                    "w-8 h-8 text-sm rounded transition",
                    i === page
                      ? "bg-blue-600 text-white"
                      : "bg-[#21262d] text-gray-300 hover:bg-[#30363d]",
                  )}
                >
                  {i + 1}
                </button>
              ))}
              <button
                type="button"
                onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
                disabled={page >= totalPages - 1}
                className="px-3 py-1.5 text-sm rounded bg-[#21262d] text-gray-300 hover:bg-[#30363d] disabled:opacity-40 transition"
              >
                下一页
              </button>
            </div>
          )}
        </>
      )}

      {/* Create Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
          <div className="bg-[#161b22] border border-[#30363d] rounded-xl p-6 w-full max-w-lg">
            <h2 className="text-lg font-bold mb-4">创建 Agent</h2>
            <div className="space-y-3">
              <div>
                <label className="text-sm text-gray-400 block mb-1">
                  名称 *
                </label>
                <input
                  type="text"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder="例如：性能分析 Agent"
                  className="w-full px-3 py-2 bg-[#0d1117] border border-[#30363d] rounded text-sm text-white focus:outline-none focus:border-blue-500"
                />
              </div>
              <div>
                <label className="text-sm text-gray-400 block mb-1">描述</label>
                <input
                  type="text"
                  value={newDesc}
                  onChange={(e) => setNewDesc(e.target.value)}
                  placeholder="Agent 的功能描述"
                  className="w-full px-3 py-2 bg-[#0d1117] border border-[#30363d] rounded text-sm text-white focus:outline-none focus:border-blue-500"
                />
              </div>
              <div>
                <label className="text-sm text-gray-400 block mb-1">分类</label>
                <input
                  type="text"
                  value={newCategory}
                  onChange={(e) => setNewCategory(e.target.value)}
                  placeholder="例如：performance, development"
                  className="w-full px-3 py-2 bg-[#0d1117] border border-[#30363d] rounded text-sm text-white focus:outline-none focus:border-blue-500"
                />
              </div>
              <div>
                <label className="text-sm text-gray-400 block mb-1">
                  标签（逗号分隔）
                </label>
                <input
                  type="text"
                  value={newTags}
                  onChange={(e) => setNewTags(e.target.value)}
                  placeholder="例如：perfetto, android, trace"
                  className="w-full px-3 py-2 bg-[#0d1117] border border-[#30363d] rounded text-sm text-white focus:outline-none focus:border-blue-500"
                />
              </div>
              <div>
                <label className="text-sm text-gray-400 block mb-1">
                  系统提示词
                </label>
                <textarea
                  value={newPrompt}
                  onChange={(e) => setNewPrompt(e.target.value)}
                  rows={4}
                  placeholder="Agent 的系统提示词，定义其行为和能力..."
                  className="w-full px-3 py-2 bg-[#0d1117] border border-[#30363d] rounded text-sm text-white focus:outline-none focus:border-blue-500 resize-none"
                />
              </div>
            </div>
            <div className="flex justify-end gap-3 mt-6">
              <button
                type="button"
                onClick={() => setShowCreateModal(false)}
                className="px-4 py-2 text-sm text-gray-400 hover:text-white transition"
              >
                取消
              </button>
              <button
                type="button"
                onClick={handleCreate}
                disabled={!newName.trim() || creating}
                className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 rounded-lg text-sm font-medium transition"
              >
                {creating ? "创建中..." : "创建"}
              </button>
            </div>
          </div>
        </div>
      )}
      {/* Git Import Modal */}
      {showImportModal && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
          <div className="bg-[#161b22] border border-[#30363d] rounded-xl p-6 w-full max-w-lg max-h-[90vh] overflow-auto">
            <h2 className="text-lg font-bold mb-4">从 Git 导入 Agent</h2>
            <p className="text-sm text-gray-400 mb-4">
              从 Git 仓库导入 Workflow + Skill 文件，自动创建 Agent。
              仓库需包含符合规范的 .md 文件。
            </p>

            {importResult ? (
              <div className="space-y-3">
                {importResult.agent_name ? (
                  <div className="bg-green-900/20 border border-green-800 rounded-lg p-4">
                    <p className="text-green-400 font-medium">导入成功</p>
                    <p className="text-sm text-gray-300 mt-2">
                      Agent: {importResult.agent_name}
                    </p>
                    <p className="text-sm text-gray-300">
                      Skills: {importResult.skill_count} 个
                    </p>
                    {importResult.workflow_name && (
                      <p className="text-sm text-gray-300">
                        Workflow: {importResult.workflow_name}
                      </p>
                    )}
                  </div>
                ) : (
                  <div className="bg-red-900/20 border border-red-800 rounded-lg p-4">
                    <p className="text-red-400 font-medium">导入失败</p>
                    <p className="text-sm text-gray-300 mt-2">
                      {importResult.workflow_name}
                    </p>
                  </div>
                )}
                <div className="flex justify-end">
                  <button
                    type="button"
                    onClick={closeImportModal}
                    className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg text-sm font-medium transition"
                  >
                    关闭
                  </button>
                </div>
              </div>
            ) : (
              <div className="space-y-3">
                <div>
                  <label className="text-sm text-gray-400 block mb-1">
                    Git 仓库地址 *
                  </label>
                  <input
                    type="text"
                    value={gitUrl}
                    onChange={(e) => setGitUrl(e.target.value)}
                    placeholder="https://gitlab.example.com/team/skills.git"
                    className="w-full px-3 py-2 bg-[#0d1117] border border-[#30363d] rounded text-sm text-white placeholder:text-gray-500 focus:outline-none focus:border-blue-500"
                  />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-sm text-gray-400 block mb-1">
                      分支
                    </label>
                    <input
                      type="text"
                      value={gitBranch}
                      onChange={(e) => setGitBranch(e.target.value)}
                      placeholder="main"
                      className="w-full px-3 py-2 bg-[#0d1117] border border-[#30363d] rounded text-sm text-white placeholder:text-gray-500 focus:outline-none focus:border-blue-500"
                    />
                  </div>
                  <div>
                    <label className="text-sm text-gray-400 block mb-1">
                      子目录（可选）
                    </label>
                    <input
                      type="text"
                      value={gitSubdir}
                      onChange={(e) => setGitSubdir(e.target.value)}
                      placeholder="例如 skills/"
                      className="w-full px-3 py-2 bg-[#0d1117] border border-[#30363d] rounded text-sm text-white placeholder:text-gray-500 focus:outline-none focus:border-blue-500"
                    />
                  </div>
                </div>
                <div>
                  <label className="text-sm text-gray-400 block mb-1">
                    Access Token（私有仓库）
                  </label>
                  <input
                    type="password"
                    value={gitToken}
                    onChange={(e) => setGitToken(e.target.value)}
                    placeholder="留空表示公开仓库"
                    className="w-full px-3 py-2 bg-[#0d1117] border border-[#30363d] rounded text-sm text-white placeholder:text-gray-500 focus:outline-none focus:border-blue-500"
                  />
                </div>
                <hr className="border-[#30363d]" />
                <div>
                  <label className="text-sm text-gray-400 block mb-1">
                    Agent 名称（可选，自动推导）
                  </label>
                  <input
                    type="text"
                    value={gitAgentName}
                    onChange={(e) => setGitAgentName(e.target.value)}
                    placeholder="留空则从 workflow 文件名推导"
                    className="w-full px-3 py-2 bg-[#0d1117] border border-[#30363d] rounded text-sm text-white placeholder:text-gray-500 focus:outline-none focus:border-blue-500"
                  />
                </div>
                <div>
                  <label className="text-sm text-gray-400 block mb-1">
                    描述（可选）
                  </label>
                  <input
                    type="text"
                    value={gitAgentDesc}
                    onChange={(e) => setGitAgentDesc(e.target.value)}
                    placeholder="Agent 功能描述"
                    className="w-full px-3 py-2 bg-[#0d1117] border border-[#30363d] rounded text-sm text-white placeholder:text-gray-500 focus:outline-none focus:border-blue-500"
                  />
                </div>
                <div>
                  <label className="text-sm text-gray-400 block mb-1">
                    分类（可选）
                  </label>
                  <input
                    type="text"
                    value={gitAgentCategory}
                    onChange={(e) => setGitAgentCategory(e.target.value)}
                    placeholder="例如：运维、开发、测试"
                    className="w-full px-3 py-2 bg-[#0d1117] border border-[#30363d] rounded text-sm text-white placeholder:text-gray-500 focus:outline-none focus:border-blue-500"
                  />
                </div>
                <div className="flex justify-end gap-3 mt-4">
                  <button
                    type="button"
                    onClick={closeImportModal}
                    className="px-4 py-2 text-sm text-gray-400 hover:text-white transition"
                  >
                    取消
                  </button>
                  <button
                    type="button"
                    onClick={handleImport}
                    disabled={!gitUrl.trim() || importing}
                    className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 rounded-lg text-sm font-medium transition"
                  >
                    {importing ? "导入中..." : "开始导入"}
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
