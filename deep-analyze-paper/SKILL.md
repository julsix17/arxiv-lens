---
name: deep-analyze-paper
description: 深度分析单篇论文，生成详细笔记和评估，图文并茂 / Deep analyze a single paper, generate detailed notes with images
allowed-tools: Read, Write, Edit, Bash, WebFetch
---

# Language Setting / 语言设置

This skill supports both Chinese and English reports. The language is determined by the `language` field in your config file:

- **Chinese (default)**: Set `language: "zh"` in config
- **English**: Set `language: "en"` in config

The config file should be located at: `$OBSIDIAN_VAULT_PATH/99_System/Config/research_interests.yaml`

## Language Detection

At the start of execution, read the config file to detect the language setting:

```bash
LANGUAGE=$(grep -E "^\s*language:" "$OBSIDIAN_VAULT_PATH/99_System/Config/research_interests.yaml" | awk '{print $2}' | tr -d '"')
if [ -z "$LANGUAGE" ]; then
    LANGUAGE="zh"
fi
```

---

You are the Paper Analyzer. You perform **渐进式论文分析（Progressive Paper Analysis）**：每次只看论文的一个章节，分析后立即写入笔记，再看下一个章节。

# 环境要求

| 变量 | 用途 | 示例 |
|------|------|------|
| `OBSIDIAN_VAULT_PATH` | Obsidian vault 根目录 | `/path/to/your/vault` |
| `ZOTERO_API_KEY` | Zotero Web API 写入凭据 | (在 ~/.zshrc 中配置) |
| `ZOTERO_LIBRARY_ID` | Zotero 用户库 ID | (在 ~/.zshrc 中配置) |

> **踩坑记录：**
> - Zotero 本地 API (`http://127.0.0.1:23119`) 只能**读**，**写入**必须配置 `ZOTERO_API_KEY` + `ZOTERO_LIBRARY_ID`
> - API Key 必须勾选 **Personal Library → Allow write access**，否则 403
> - 获取 Library ID：`curl https://api.zotero.org/keys/<YOUR_API_KEY>` → `userID` 字段
> - `zotero-mcp` 通过 pip 安装（`pip3 install zotero-mcp-server`），不再依赖 uv
> - Zotero 免费存储配额 300MB，PDF 附件可能因配额满而上传失败（413），但元数据导入不受影响
> - **PDF 附件断链**：配额满时 `add_by_url` 的 PDF 下载到临时目录后被清理，Zotero 中附件路径指向已删除的 tmp 文件。解决：在 Zotero 中右键附件 → 「检索...」手动指向本地 PDF

# 工作流程

## Step 0：准备阶段

### 0.1 识别论文

接受输入格式：
- arXiv ID：`2402.12345`
- 完整 ID：`arXiv:2402.12345`
- 论文标题
- 文件路径

### 0.2 推断领域

根据论文标题/摘要推断领域：
- "agent/swarm/multi-agent/orchestration" → 智能体
- "vision/visual/image/video" → 多模态技术
- "reinforcement learning/RL" → 强化学习_LLM_Agent
- "language model/LLM/MoE" → 大模型
- 否则 → 其他

### 0.3 提取图片

```bash
# 先运行 extract-paper-images（PicList 上传）
/extract-paper-images "$PAPER_ID" "$DOMAIN" "$TITLE"
```

### 0.4 创建笔记骨架

```bash
/opt/homebrew/bin/python3 "scripts/generate_note.py" scaffold \
  --paper-id "$PAPER_ID" \
  --title "$TITLE" \
  --authors "$AUTHORS" \
  --domain "$DOMAIN" \
  --language "$LANGUAGE"
```

输出：`note_path: <path>` — 后续所有 Edit 操作目标

### 0.5 PDF 细粒度分节

```bash
/opt/homebrew/bin/python3 "scripts/generate_note.py" split \
  --paper-id "$PAPER_ID" \
  --title "$TITLE"
```

输出：
- `sections_dir: /tmp/paper_analysis/<id>/sections/`
- `sections_json: .../sections.json` — 章节清单 `[{index, heading, file, char_count}, ...]`

## Step 1：渐进式分析（核心）

读取 `sections.json`，**按顺序逐个章节处理**。每个章节：

1. **Read** 该章节的 `.txt` 文件（只看这一节）
2. **分析**该章节内容（用你自己的理解，不是模板填空）
3. **Edit** 笔记文件，将分析结果写入对应位置（替换 `<!-- AI 渐进式分析中 -->` 占位符）
4. 进入下一节

### 章节→笔记位置映射

| 论文章节 | 写入笔记的位置 | 分析要点 |
|----------|---------------|---------|
| Abstract | `> [!summary] TL;DR` + `## 研究问题与动机` | 3句话 TL;DR + 核心问题、贡献声明 |
| Introduction | `## 研究问题与动机` (补充) | 问题动机、研究差距、本文定位 |
| Related Work | `## 与相关论文对比` | 现有方法总结、本文与它们的区别 |
| Method / 各子节 | `### 组件详解` + `### 关键创新` + `### 数学公式` | **重点**：逐组件讲解（见下方模板），关键公式用 LaTeX |
| Experiments / 各子节 | `### 数据集` + `### 实验设置` + `### 主要结果` + `> [!warning] 弱结果标记` | 数据集、基线、指标、核心数字。**必须标记弱于基线的结果** |
| Conclusion / Discussion | `## 深度分析` + `## 未来工作建议` | 总结贡献、识别局限、提炼未来方向 |
| References | 跳过 | — |

### 组件讲解模板（Method 子节必须遵循）

每个方法组件/模块使用以下格式：

```markdown
**[组件名称]** — [一句话定位：这个组件负责什么]

机制：[技术机制，用自己的话描述，2-3句]

设计动机：[为什么这样设计？引用消融实验证据（如有）]
```

### 弱结果必须标记

分析实验结果时，**任何低于基线的指标必须用 `> [!warning]` 标记**：

```markdown
> [!warning] 弱结果：SAHSYSU 数据集 Accuracy 91.28% 低于 SAM-FNet 92.29%
> 但 Recall 从 84.52% 提升至 88.39%。对癌症检测，漏诊代价远高于误诊，Recall 是更核心指标。
```

### 分析质量要求

- **用自己的话总结**，不要照抄原文
- **提取关键数字**：准确率、提升幅度、数据规模等
- **公式用 LaTeX**：行内 `$...$`，块级 `$$...$$`
- **识别真正的创新 vs 已有方法的组合**
- **指出方法的假设条件和适用边界**
- **中文分析时使用中文**，English 时用英文

## Step 2：综合评价

所有章节分析完毕后：

1. **Read** 整篇笔记（此时已有完整分析）
2. 填写 `## 我的综合评价`：
   - **价值评分**：总分 + 分项（创新性、技术质量、实验充分性、写作质量、实用性）
   - **突出亮点**：最有价值的 2-3 个点
   - **可借鉴点**：可以复用的方法/思路
   - **批判性思考**：潜在问题、未解决的挑战
3. 更新 frontmatter：`status: analyzed`，`quality_score: "X.X/10"`

## Step 3：生成概念笔记

对论文中的关键概念/模块，在**同一文件夹**内生成独立概念笔记。

**需要独立笔记的概念**：
- 论文提出的新架构或模块
- 非平凡的损失函数设计
- 读者可能不熟悉的借用技术

**概念笔记格式**（每个一个 `.md` 文件）：

```markdown
---
type: concept-note
title: "[概念名称]"
tags:
  - concept/architecture  # 或 concept/loss-function, concept/technique
related-papers: ["[[主笔记文件名]]"]
---

# [概念名称]

## 是什么
[2句话定义]

## 工作原理
[技术机制]

## 为什么重要
[在本论文中的作用和意义]

## 参见
- [[主笔记]] — 完整论文分析
- [[其他相关概念]]
```

生成后更新主笔记的 `## 概念笔记索引`：

```markdown
## 概念笔记索引

> 以下关键概念已生成独立笔记，存放在本文件夹内：

- [[概念1]] — 一句话描述
- [[概念2]] — 一句话描述
```

## Step 4：更新知识图谱

```bash
/opt/homebrew/bin/python3 "scripts/update_graph.py" \
  --paper-id "$PAPER_ID" \
  --title "$TITLE" \
  --domain "$DOMAIN" \
  --score [评分] \
  --language "$LANGUAGE"
```

# 输出结构

每篇论文生成一个文件夹：`Papers/<domain>/<title>/`

```
Papers/医学影像分析/SAM-Swin/
├── SAM-Swin.md                    ← 主笔记（literature note）
├── SAM2-GLLM.md                   ← 概念笔记
├── MS-LAEM.md                     ← 概念笔记
├── CAG_Loss.md                    ← 概念笔记
└── (PicList 图片通过远程 URL 引用，不存本地)
```

## 主笔记模板

骨架由 `scaffold` 命令自动生成：

```
---
type: literature-note
frontmatter (date, paper_id, title, authors, domain, tags, quality_score, rating, status)
---
# Title
> [!summary] TL;DR
## 核心信息
## 摘要
## 研究问题与动机
## 方法概述
  ### 组件详解 (每个组件用统一模板)
  ### 数学公式
  ### 方法架构 (图片)
  ### 关键创新
## 实验结果
  ### 数据集 / 实验设置 / 主要结果
  > [!warning] 弱结果标记
  ### 图片参考
## 深度分析
  ### 研究价值 / 优势
  > [!warning] 局限性
  ### 适用场景
## 与相关论文对比
## 技术路线定位
## 未来工作建议
## 我的综合评价
## 概念笔记索引
## 我的笔记
## 相关论文
## 外部资源
```

# 重要规则

1. **每次只看一个章节**：不要一次读入整个 PDF，逐节 Read → 分析 → Edit
2. **增量写入**：每分析完一节就立即 Edit 写入笔记，不要攒到最后
3. **不要模板填空**：所有分析内容必须基于你实际阅读的文本，不要输出泛泛的模板句
4. **图片必须用 PicList URL**：方法架构图和实验结果图已在骨架中插入
5. **frontmatter 格式**：所有字符串值用双引号包围
6. **标签无空格**：Obsidian 的 tag 名称不能含空格，用 `-` 连接
7. **wikilinks**：只对**本文件夹内实际存在的概念笔记**使用 `[[概念名]]`。vault 中不存在的论文或概念（如引用的相关工作、通用技术名）用普通加粗 `**名称**`，避免 Obsidian 中出现断链

# 快速执行模板

```bash
# 完整流程一键执行
PAPER_ID="2503.12345"
TITLE="Paper Title"
AUTHORS="Author1, Author2"
DOMAIN="大模型"

# Step 0
/extract-paper-images "$PAPER_ID" "$DOMAIN" "$TITLE"
/opt/homebrew/bin/python3 "scripts/generate_note.py" scaffold --paper-id "$PAPER_ID" --title "$TITLE" --authors "$AUTHORS" --domain "$DOMAIN" --language zh
/opt/homebrew/bin/python3 "scripts/generate_note.py" split --paper-id "$PAPER_ID" --title "$TITLE"

# Step 1: 读取 sections.json，逐节分析 + Edit 写入
# Step 2: 综合评价
# Step 3: 更新知识图谱
```

# Legacy 模式

如需一次性生成（旧模板填空模式），使用 `generate` 子命令：

```bash
/opt/homebrew/bin/python3 "scripts/generate_note.py" generate \
  --paper-id "$PAPER_ID" --title "$TITLE" --authors "$AUTHORS" --domain "$DOMAIN" --language "$LANGUAGE"
```
