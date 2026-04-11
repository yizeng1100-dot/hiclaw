# HiClaw 本地编译部署指南

基于 OpenHands 的内网本地部署，不使用 Docker 部署应用本身，但 Docker 仍需用于运行 agent-server 容器。

## 系统要求

| 依赖 | 版本 | 说明 |
|------|------|------|
| Python | 3.12+ | 后端运行环境 |
| Node.js | 22+ | 前端构建 |
| npm | 10+ | 前端包管理 |
| Poetry | 2.x | Python 依赖管理 |
| Docker | 24+ | 运行 agent-server 容器（每个会话一个容器） |
| Claude Code CLI | 2.0+ | **可选** — 仅 Claude SDK 引擎模式需要 |

## 一键部署步骤

### 1. 克隆代码

```bash
git clone https://github.com/yizeng1100-dot/hiclaw.git
cd hiclaw
git checkout test
```

### 2. 安装 Python 依赖

```bash
# 安装 Poetry（如果没有）
curl -sSL https://install.python-poetry.org | python3 -

# 安装项目依赖
poetry install
```

### 3. 构建前端

```bash
cd frontend
npm install
npm run build
cd ..
```

### 4. 配置 LLM

首次启动后访问页面，在设置中配置 LLM 模型和 API Key。或者提前创建配置文件：

```bash
mkdir -p ~/.openhands
cat > ~/.openhands/settings.json << 'EOF'
{
  "llm_model": "你的模型名称",
  "llm_api_key": "你的API Key",
  "llm_base_url": "你的API地址（可选）"
}
EOF
```

### 5. 启动服务

```bash
# 推荐：使用启动脚本（自动处理会话持久化、Docker 检查等）
./start.sh          # 前台运行
./start.sh -d       # 后台运行
./start.sh stop     # 停止
```

或手动启动（需自行设置环境变量）：
```bash
# 会话持久化：挂载宿主机目录到容器，防止切换会话丢历史
export SANDBOX_VOLUMES="$HOME/.openhands/sandbox-data:/workspace/conversations:rw"
mkdir -p $HOME/.openhands/sandbox-data
sudo chown -R 10001:10001 $HOME/.openhands/sandbox-data

poetry run uvicorn openhands.server.listen:app --host 0.0.0.0 --port 3000
```

### 6. 访问

浏览器打开 `http://<服务器IP>:3000`

## 工作原理

```
浏览器 ──→ uvicorn (端口3000)
              │
              ├── 前端静态文件 (frontend/build/)
              ├── 后端 API
              └── 每个会话 → 启动一个 Docker 容器 (agent-server)
                              │
                              └── ghcr.io/openhands/agent-server:1.14.0-python
```

- **后端**直接运行在主机上（不在 Docker 里）
- **每个会话**会自动拉取并启动一个 `agent-server` Docker 容器
- **Skill 数据**首次启动时自动从 `custom/skill_examples/` 导入到 `~/.openhands/openhands.db`

## 常用操作

```bash
# 查看日志
tail -f /tmp/openhands.log

# 停止服务
kill $(pgrep -f "uvicorn openhands.server.listen")

# 清理 agent 容器
docker ps -a --filter "name=oh-agent-server" -q | xargs docker rm -f

# 重新构建前端（修改代码后）
cd frontend && npm run build && cd ..
```

## 目录结构

```
hiclaw/
├── custom/                    # 自定义扩展
│   ├── skill_examples/        # Skill 定义文件（启动时自动导入数据库）
│   │   ├── android-kernel-diff-analysis.md
│   │   └── kernel_diff_analysis.py
│   └── skill_mgmt/            # Skill 管理后端
├── frontend/                  # 前端代码
│   ├── src/                   # 源码
│   └── build/                 # 构建产物（npm run build 生成）
├── openhands/                 # OpenHands 核心代码
└── ~/.openhands/              # 运行时数据（数据库、设置等）
    ├── openhands.db           # SQLite 数据库（Skill、会话等）
    └── settings.json          # LLM 配置
```
