#!/usr/bin/env python3

import argparse
import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import TypedDict, cast


logger = logging.getLogger(__name__)
SECTION_START = '%% PICLIST_IMAGE_INDEX_START'
SECTION_END = 'PICLIST_IMAGE_INDEX_END %%'


class CliArgs(argparse.Namespace):
    input: str = ""
    output: str = ""
    vault: str = ""
    language: str = "zh"
    top_images: int = 3


class PaperScores(TypedDict, total=False):
    recommendation: float


class PaperData(TypedDict, total=False):
    arxiv_id: str
    id: str
    title: str
    summary: str
    authors: list[str]
    affiliations: list[str]
    url: str
    pdf_url: str
    source: str
    matched_domain: str
    matched_keywords: list[str]
    note_filename: str
    scores: PaperScores


class SearchOutput(TypedDict):
    target_date: str
    top_papers: list[PaperData]


class ImageEntry(TypedDict):
    filename: str
    url: str


def as_dict(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    raw = cast(dict[object, object], value)
    return {str(key): item for key, item in raw.items()}


def as_str(value: object, default: str = "") -> str:
    return value if isinstance(value, str) else default


def as_str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    items = cast(list[object], value)
    return [item for item in items if isinstance(item, str)]


def load_search_output(path: Path) -> SearchOutput:
    with path.open('r', encoding='utf-8') as handle:
        raw = cast(object, json.load(handle))

    data = as_dict(raw)
    top_raw = data.get('top_papers')
    top_papers = [cast(PaperData, cast(object, as_dict(item))) for item in cast(list[object], top_raw if isinstance(top_raw, list) else [])]
    return SearchOutput(target_date=as_str(data.get('target_date')), top_papers=top_papers)


def sanitize_note_filename(title: str) -> str:
    return re.sub(r'[ /\\:*?"<>|]+', '_', title).strip('_')


def format_authors(authors: list[str], language: str) -> str:
    if not authors:
        return '未指定' if language == 'zh' else 'Not specified'
    if len(authors) <= 4:
        return ', '.join(authors)
    suffix = ' 等' if language == 'zh' else ' et al.'
    return f"{', '.join(authors[:3])}{suffix}"


def format_affiliation(affiliations: list[str], language: str) -> str:
    if not affiliations:
        return '未指定' if language == 'zh' else 'Not specified'
    return affiliations[0]


def format_score(paper: PaperData) -> str:
    scores = cast(PaperScores, cast(object, as_dict(paper.get('scores'))))
    value = scores.get('recommendation')
    if isinstance(value, (int, float)):
        return f'{value:.2f}'.rstrip('0').rstrip('.')
    return 'N/A'


def note_link(paper: PaperData) -> str:
    domain = as_str(paper.get('matched_domain'), '其他')
    note_filename = as_str(paper.get('note_filename')) or sanitize_note_filename(as_str(paper.get('title')))
    return f'20_Research/Papers/{domain}/{note_filename}'


def note_path_for_paper(paper: PaperData, vault_path: Path) -> Path:
    return vault_path / f'{note_link(paper)}.md'


def output_note_name(target_date: str, language: str) -> str:
    return f'{target_date}论文推荐.md' if language == 'zh' else f'{target_date}-paper-recommendations.md'


def extract_keywords(papers: list[PaperData]) -> list[str]:
    keywords: list[str] = []
    seen: set[str] = set()
    for paper in papers:
        for keyword in as_str_list(paper.get('matched_keywords')):
            normalized = keyword.strip()
            if not normalized:
                continue
            lowered = normalized.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            keywords.append(normalized)
    return keywords[:20]


def parse_note_image_section(note_path: Path) -> list[ImageEntry]:
    entries: list[ImageEntry] = []
    if not note_path.exists():
        return entries
    content = note_path.read_text(encoding='utf-8')
    start = content.find(SECTION_START)
    end = content.find(SECTION_END)
    if start == -1 or end == -1 or end < start:
        return entries
    current_filename = ''
    for line in content[start:end].splitlines():
        if line.startswith('- 文件名：'):
            current_filename = line.removeprefix('- 文件名：').strip()
        elif line.startswith('- URL：') and current_filename:
            entries.append(ImageEntry(filename=current_filename, url=line.removeprefix('- URL：').strip()))
            current_filename = ''
    return entries


def image_priority(filename: str) -> int:
    lowered = filename.lower()
    if any(token in lowered for token in ('orcid', 'logo', 'icon')):
        return -100
    score = 0
    for token, weight in (
        ('arch', 50),
        ('framework', 45),
        ('model', 40),
        ('pipeline', 35),
        ('overview', 30),
        ('vqvae', 25),
        ('visor', 20),
    ):
        if token in lowered:
            score += weight
    return score


def choose_image_url(entries: list[ImageEntry]) -> str:
    if not entries:
        raise RuntimeError('No PicList image URLs found in image index')
    ranked = sorted(entries, key=lambda entry: image_priority(entry['filename']), reverse=True)
    return ranked[0]['url']


def read_existing_note_value(note_path: Path, labels: list[str]) -> str:
    if not note_path.exists():
        return ''
    for line in note_path.read_text(encoding='utf-8').splitlines():
        stripped = line.strip()
        for label in labels:
            prefix = f'**{label}**：'
            if stripped.startswith(prefix):
                return stripped.removeprefix(prefix).strip()
            prefix_en = f'**{label}**: '
            if stripped.startswith(prefix_en):
                return stripped.removeprefix(prefix_en).strip()
    return ''


def detect_paper_kind(summary: str, title: str) -> str:
    text = f'{title} {summary}'.lower()
    if any(token in text for token in ('benchmark', 'evaluation', 'exposing', 'safety', 'triage')):
        return 'benchmark'
    if any(token in text for token in ('efficient', 'efficiency', 'sparse', 'routing', 'acceleration')):
        return 'efficiency'
    if any(token in text for token in ('ct', 'mri', 'x-ray', 'ultrasound', 'medical')):
        return 'medical'
    if any(token in text for token in ('video', 'tactile', 'robot', 'action', 'embodied')):
        return 'embodied'
    return 'method'


def chinese_summary_from_metadata(paper: PaperData) -> str:
    title = as_str(paper.get('title'))
    summary = as_str(paper.get('summary'))
    kind = detect_paper_kind(summary, title)
    if kind == 'benchmark':
        return '提出面向该问题的新评测基准或安全分析框架，突出模型在真实场景下的能力边界。'
    if kind == 'efficiency':
        return '围绕模型效率优化提出新方法，在尽量保持性能的同时降低计算或推理开销。'
    if kind == 'medical':
        return '聚焦医学影像任务，提出更贴近临床场景的建模或评估方法。'
    if kind == 'embodied':
        return '面向具身/交互场景提出多模态建模方法，强化感知与动作协同能力。'
    return '提出新的方法框架，并通过实验验证其在目标任务上的有效性。'


def shorten_text(text: str, limit: int = 70) -> str:
    cleaned = ' '.join(text.replace('\n', ' ').split())
    if len(cleaned) <= limit:
        return cleaned
    for separator in ('。', '. ', '; ', '；', ', '):
        idx = cleaned.find(separator)
        if 0 < idx <= limit:
            return cleaned[:idx + (1 if separator == '。' else 0)].strip()
    return cleaned[:limit].rstrip(' ,;，；。') + '…'


def derive_one_line_summary(paper: PaperData, vault_path: Path, language: str) -> str:
    if language == 'zh':
        return chinese_summary_from_metadata(paper)
    note_path = note_path_for_paper(paper, vault_path)
    existing = read_existing_note_value(note_path, ['一句话总结', 'One-line Summary'])
    if existing:
        return shorten_text(existing, 42 if language == 'zh' else 80)
    summary = as_str(paper.get('summary')).strip()
    if summary:
        return shorten_text(summary, 42 if language == 'zh' else 80)
    title = as_str(paper.get('title'))
    return shorten_text(title, 36 if language == 'zh' else 72)


def derive_key_result(paper: PaperData, vault_path: Path, language: str) -> str:
    note_path = note_path_for_paper(paper, vault_path)
    existing = read_existing_note_value(note_path, ['关键结果', 'Key Results'])
    if existing:
        return existing
    domain = as_str(paper.get('matched_domain'), '该方向' if language == 'zh' else 'this area')
    score = format_score(paper)
    if language == 'zh':
        return f'推荐评分 {score}，匹配领域为{domain}。'
    return f'Recommendation score {score}, matched domain: {domain}.'


def ensure_piclist_image(paper: PaperData, vault_path: Path, extract_script: Path) -> str:
    domain = as_str(paper.get('matched_domain'), '其他')
    note_filename = as_str(paper.get('note_filename')) or sanitize_note_filename(as_str(paper.get('title')))
    arxiv_id = as_str(paper.get('arxiv_id'))
    if not arxiv_id:
        raw_id = as_str(paper.get('id'))
        match = re.search(r'(\d{4}\.\d+)', raw_id)
        if match:
            arxiv_id = match.group(1)
    if not arxiv_id:
        raise RuntimeError(f"Missing arXiv ID for paper: {as_str(paper.get('title'))}")

    note_path = vault_path / '20_Research' / 'Papers' / domain / f'{note_filename}.md'
    note_path.parent.mkdir(parents=True, exist_ok=True)

    command = [
        sys.executable,
        str(extract_script),
        arxiv_id,
        str(note_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"PicList image extraction failed for {as_str(paper.get('title'))}:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    entries = parse_note_image_section(note_path)
    if not entries:
        raise RuntimeError(f'PicList URL section missing after extraction: {note_path}')
    return choose_image_url(entries)


def summarize_overview(papers: list[PaperData], language: str) -> str:
    top_domains: list[str] = []
    seen: set[str] = set()
    for paper in papers:
        domain = as_str(paper.get('matched_domain'))
        if domain and domain not in seen:
            seen.add(domain)
            top_domains.append(domain)
    if not top_domains:
        top_domains = ['综合研究'] if language == 'zh' else ['mixed topics']

    if language == 'zh':
        joined = '、'.join(f'**{domain}**' for domain in top_domains[:3])
        scores = [format_score(p) for p in papers if format_score(p) != 'N/A']
        score_range = f'{scores[-1]}-{scores[0]}' if scores else 'N/A'
        return (
            '## 今日概览\n\n'
            f'今日推荐的{len(papers)}篇论文主要聚焦于{joined}等方向。\n\n'
            f'- **总体趋势**：高分论文集中在医学视觉、多模态推理效率与安全评估等主题。\n\n'
            f'- **质量分布**：今日推荐论文评分范围为 {score_range}，整体质量较高。\n\n'
            f'- **阅读建议**：优先阅读前3篇，随后按研究兴趣选择其余论文。\n'
        )

    joined = ', '.join(top_domains[:3])
    return (
        '## Overview\n\n'
        f"Today's {len(papers)} recommended papers mainly focus on {joined}.\n\n"
        '- **Trend**: top-ranked papers cluster around medical vision, multimodal reasoning efficiency, and safety evaluation.\n\n'
        '- **Reading order**: start with the top 3 papers, then continue based on your interests.\n'
    )


def build_section(paper: PaperData, image_url: str | None, language: str, include_report: bool, vault_path: Path) -> str:
    title = as_str(paper.get('title'))
    note_filename = as_str(paper.get('note_filename')) or sanitize_note_filename(title)
    display_title = f'[[{note_filename}|{title}]]'
    authors = format_authors(as_str_list(paper.get('authors')), language)
    affiliation = format_affiliation(as_str_list(paper.get('affiliations')), language)
    arxiv_url = as_str(paper.get('url'))
    pdf_url = as_str(paper.get('pdf_url'))
    one_line_summary = derive_one_line_summary(paper, vault_path, language)
    key_result = derive_key_result(paper, vault_path, language)
    score = format_score(paper)
    domain = as_str(paper.get('matched_domain'), '其他')
    report_link = f'[[{note_link(paper)}]]'

    if language == 'zh':
        lines = [
            f'### {display_title}',
            f'- **作者**：{authors}',
            f'- **机构**：{affiliation}',
            f'- **链接**：[arXiv]({arxiv_url}) | [PDF]({pdf_url})',
            f'- **来源**：{as_str(paper.get("source"), "arXiv")}',
        ]
        lines.append(f'- **详细报告**：{report_link}' if include_report else f'- **笔记**：{report_link}')
        lines.extend([
            '',
            f'**一句话总结**：{one_line_summary}',
            '',
        ])
        if image_url is not None:
            lines.extend([f'![{note_filename}|600]({image_url})', ''])
        lines.extend([
            '**核心贡献/观点**：',
            f'- 匹配领域：{domain}',
            f'- 推荐评分：{score}',
            f'- 匹配关键词：{", ".join(as_str_list(paper.get("matched_keywords"))) or "—"}',
            '',
            f'**关键结果**：{key_result}',
            '',
            '---',
            '',
        ])
        return '\n'.join(lines)

    lines = [
        f'### {display_title}',
        f'- **Authors**: {authors}',
        f'- **Affiliation**: {affiliation}',
        f'- **Links**: [arXiv]({arxiv_url}) | [PDF]({pdf_url})',
        f'- **Source**: {as_str(paper.get("source"), "arXiv")}',
    ]
    lines.append(f'- **Detailed Report**: {report_link}' if include_report else f'- **Notes**: {report_link}')
    lines.extend([
        '',
        f'**One-line Summary**: {one_line_summary}',
        '',
    ])
    if image_url is not None:
        lines.extend([f'![{note_filename}|600]({image_url})', ''])
    lines.extend([
        '**Core Contributions**:',
        f'- Domain: {domain}',
        f'- Recommendation score: {score}',
        f'- Matched keywords: {", ".join(as_str_list(paper.get("matched_keywords"))) or "—"}',
        '',
        f'**Key Results**: {key_result}',
        '',
        '---',
        '',
    ])
    return '\n'.join(lines)


def generate_note(search_output: SearchOutput, vault_path: Path, language: str) -> str:
    papers = search_output['top_papers']
    if not papers:
        raise RuntimeError('No papers available to generate daily note')

    script_dir = Path(__file__).resolve().parent
    extract_script = script_dir.parent.parent / 'extract-paper-images' / 'scripts' / 'extract_images.py'
    if not extract_script.exists():
        raise RuntimeError(f'PicList image extractor not found: {extract_script}')

    image_urls: dict[int, str] = {}
    top_image_count = min(3, len(papers))
    for index in range(top_image_count):
        image_urls[index] = ensure_piclist_image(papers[index], vault_path, extract_script)

    keywords = extract_keywords(papers)
    if language == 'zh':
        frontmatter = (
            '---\n'
            f'keywords: [{", ".join(keywords)}]\n'
            'tags: ["llm-generated", "daily-paper-recommend"]\n'
            '---\n\n'
        )
    else:
        frontmatter = (
            '---\n'
            f'keywords: [{", ".join(keywords)}]\n'
            'tags: ["llm-generated", "daily-paper-recommend"]\n'
            '---\n\n'
        )

    sections = [build_section(paper, image_urls.get(index), language, include_report=index < 3, vault_path=vault_path) for index, paper in enumerate(papers)]
    return frontmatter + summarize_overview(papers, language) + '\n\n---\n\n' + ''.join(sections)


def main() -> int:
    parser = argparse.ArgumentParser(description='Generate start-my-day daily note with PicList-backed images')
    _ = parser.add_argument('--input', type=str, required=True, help='Path to arxiv_filtered.json')
    _ = parser.add_argument('--output', type=str, required=False, help='Output markdown file path')
    _ = parser.add_argument('--vault', type=str, default=os.environ.get('OBSIDIAN_VAULT_PATH', ''), help='Obsidian vault path')
    _ = parser.add_argument('--language', type=str, default='zh', choices=['zh', 'en'], help='Output language')
    _ = parser.add_argument('--top-images', type=int, default=3, help='Reserved for future use')
    args = cast(CliArgs, cast(object, parser.parse_args()))

    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S', stream=sys.stderr)

    if not args.vault:
        logger.error('Missing vault path')
        return 1

    search_output = load_search_output(Path(args.input))
    target_date = search_output['target_date']
    output_path = Path(args.output) if args.output else Path(args.vault) / '10_Daily' / output_note_name(target_date, args.language)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    content = generate_note(search_output, Path(args.vault), args.language)
    _ = output_path.write_text(content, encoding='utf-8')
    logger.info('Daily note saved to: %s', output_path)
    return 0


if __name__ == '__main__':
    sys.exit(main())
