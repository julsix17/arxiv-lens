# arxiv-lens

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
# Clone into Claude Code skills directory
git clone https://github.com/<your-username>/arxiv-lens.git ~/.claude/skills

# Or symlink if you keep skills elsewhere
ln -s /path/to/arxiv-lens/* ~/.claude/skills/
```

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
