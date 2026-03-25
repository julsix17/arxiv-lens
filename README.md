# arxiv-lens

[English](#english) | [中文](#中文)

---

<a id="english"></a>

A set of [Claude Code](https://docs.anthropic.com/en/docs/claude-code) skills for discovering, analyzing, and organizing research papers into an Obsidian vault.

## Skills

### `/paper-search`
Search arXiv + Semantic Scholar for recent and trending papers based on your research interests. Generates a daily recommendation note in Obsidian with ranked papers, relevance scores, and reading suggestions. You decide which papers to deep-dive into.

### `/deep-analyze-paper`
Progressive, section-by-section analysis of a single paper. Reads one chapter at a time, writes analysis to the note, then moves to the next. Outputs a folder per paper:

```
Papers/<domain>/<paper_title>/
├── <paper_title>.md       # Literature note (with callouts, LaTeX, images)
├── Module_A.md            # Concept note
├── Module_B.md            # Concept note
└── Loss_Function.md       # Concept note
```

Features:
- `> [!summary]` TL;DR callout
- Component walk-through with unified template (name → mechanism → design motivation)
- `> [!warning]` mandatory weak result flagging
- Auto-generated concept notes for key modules/techniques
- Images via PicList (remote URL, no local storage)

### `/extract-paper-images`
Extract figures from arXiv source packages or PDF, upload to PicList, and index URLs in the note. All images are referenced via remote URL — no local `images/` folders.

### `/conf-papers`
Search top conference proceedings (CVPR, ICCV, ECCV, ICLR, NeurIPS, ICML, AAAI) for papers matching your research interests.

## Workflow

```
/paper-search          → Daily recommendation note (10 ranked papers)
                           ↓ You pick one
/deep-analyze-paper    → Progressive analysis → Literature note + Concept notes
```

## Setup

### Requirements

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) CLI
- Python 3.13+ (`/opt/homebrew/bin/python3`)
- [PyMuPDF](https://pymupdf.readthedocs.io/) (`pip install pymupdf`)
- [PicList](https://piclist.cn/) running at `http://127.0.0.1:36677`
- [Obsidian](https://obsidian.md/) vault

### Environment Variables (~/.zshrc)

```bash
export OBSIDIAN_VAULT_PATH="/path/to/your/obsidian/vault"
export ZOTERO_API_KEY="your_key"          # Optional: Zotero integration
export ZOTERO_LIBRARY_ID="your_id"        # Optional: Zotero integration
```

### Installation

```bash
# Clone the repo somewhere
git clone https://github.com/julsix17/arxiv-lens.git

# Symlink each skill into Claude Code skills directory
for skill in arxiv-lens/paper-search arxiv-lens/deep-analyze-paper arxiv-lens/extract-paper-images arxiv-lens/conf-papers; do
  ln -s "$(pwd)/$skill" ~/.claude/skills/
done
```

Or manually copy the skill folders you need into `~/.claude/skills/`.

### Research Interests Config

Create `$OBSIDIAN_VAULT_PATH/99_System/Config/research_interests.yaml`:

```yaml
language: "zh"   # or "en"

research_domains:
  "Your Domain":
    keywords:
      - "keyword1"
      - "keyword2"
    arxiv_categories:
      - "cs.CV"
      - "cs.AI"
    priority: 5
```

## Vault Structure

```
vault/
├── 10_Daily/
│   └── YYYY-MM-DD-paper-recommendations.md   # Daily recommendations
├── 20_Research/
│   └── Papers/
│       └── <domain>/
│           └── <paper_title>/
│               ├── <paper_title>.md   # Literature note
│               ├── Concept1.md        # Concept notes
│               └── Concept2.md
└── 99_System/
    └── Config/
        └── research_interests.yaml
```

## License

MIT

---

<a id="中文"></a>

# arxiv-lens

一套 [Claude Code](https://docs.anthropic.com/en/docs/claude-code) 技能，用于发现、深度分析论文并整理到 Obsidian 知识库中。

## 技能

### `/paper-search`
搜索 arXiv + Semantic Scholar 的最新和热门论文，根据你的研究兴趣生成每日推荐笔记。包含排名、评分、相关性说明。由你决定深入分析哪篇。

### `/deep-analyze-paper`
渐进式逐章节论文分析。每次只读一个章节，分析后写入笔记，再读下一个。每篇论文输出一个文件夹：

```
Papers/<领域>/<论文标题>/
├── <论文标题>.md        # 主笔记（含 callout、LaTeX、图片）
├── 模块A.md             # 概念笔记
├── 模块B.md             # 概念笔记
└── 损失函数.md          # 概念笔记
```

特性：
- `> [!summary]` TL;DR 摘要 callout
- 统一组件讲解模板（名称 → 机制 → 设计动机）
- `> [!warning]` 强制标记弱于基线的结果
- 自动生成关键模块/技术的概念笔记
- 图片通过 PicList 远程 URL 引用，不存本地

### `/extract-paper-images`
从 arXiv 源码包或 PDF 中提取论文图片，上传到 PicList，在笔记中索引 URL。

### `/conf-papers`
搜索顶会论文（CVPR、ICCV、ECCV、ICLR、NeurIPS、ICML、AAAI），根据研究兴趣筛选推荐。

## 工作流

```
/paper-search          → 每日推荐笔记（10 篇排名论文）
                           ↓ 你选一篇
/deep-analyze-paper    → 渐进式分析 → 主笔记 + 概念笔记
```

## 配置

### 依赖

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) CLI
- Python 3.13+
- [PyMuPDF](https://pymupdf.readthedocs.io/)（`pip install pymupdf`）
- [PicList](https://piclist.cn/) 运行在 `http://127.0.0.1:36677`
- [Obsidian](https://obsidian.md/) 知识库

### 环境变量（~/.zshrc）

```bash
export OBSIDIAN_VAULT_PATH="/path/to/your/obsidian/vault"
export ZOTERO_API_KEY="your_key"          # 可选：Zotero 集成
export ZOTERO_LIBRARY_ID="your_id"        # 可选：Zotero 集成
```

### 安装

```bash
# 克隆到任意位置
git clone https://github.com/julsix17/arxiv-lens.git

# 将各技能符号链接到 Claude Code skills 目录
for skill in arxiv-lens/paper-search arxiv-lens/deep-analyze-paper arxiv-lens/extract-paper-images arxiv-lens/conf-papers; do
  ln -s "$(pwd)/$skill" ~/.claude/skills/
done
```

或手动将需要的 skill 文件夹复制到 `~/.claude/skills/`。

### 研究兴趣配置

创建 `$OBSIDIAN_VAULT_PATH/99_System/Config/research_interests.yaml`：

```yaml
language: "zh"   # 或 "en"

research_domains:
  "你的研究领域":
    keywords:
      - "关键词1"
      - "关键词2"
    arxiv_categories:
      - "cs.CV"
      - "cs.AI"
    priority: 5
```

## Vault 结构

```
vault/
├── 10_Daily/
│   └── YYYY-MM-DD-paper-recommendations.md   # 每日推荐
├── 20_Research/
│   └── Papers/
│       └── <领域>/
│           └── <论文标题>/
│               ├── <论文标题>.md   # 主笔记
│               ├── 概念1.md       # 概念笔记
│               └── 概念2.md
└── 99_System/
    └── Config/
        └── research_interests.yaml
```

## 许可

MIT
