---
name: workflow-generator
description: 从已有脚本自动生成 workflow 的 SKILL.md 和目录结构
type: skill
trigger:
  type: keyword
  keywords: ["generate workflow", "create workflow", "生成workflow", "整理脚本"]
scripts: []
---

# Workflow Generator

当用户要求从已有脚本生成 workflow 时：

1. **扫描目录** — 读取目标目录下所有脚本文件
2. **分析每个脚本** — 理解功能、输入输出、依赖
3. **确定执行顺序** — 根据命名、依赖关系、逻辑流程
4. **生成 SKILL.md** — 按照 `_templates/workflow-template.md` 格式
5. **确认** — 让用户审查后再保存

SKILL.md 必须包含：
- frontmatter: name, description, type: workflow, trigger, depends_on
- 每个步骤：做什么、运行什么脚本、输入输出
