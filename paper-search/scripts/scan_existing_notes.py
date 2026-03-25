#!/usr/bin/env python3
"""
扫描现有笔记构建索引
用于 start-my-day skill，扫描 vault 中的现有笔记并构建关键词到笔记路径的映射表
"""

import os
import re
import json
import sys
import argparse
import logging
from pathlib import Path
from typing import TypedDict, cast
import yaml

from common_words import COMMON_WORDS

logger = logging.getLogger(__name__)


type FrontmatterData = dict[str, object]
type TagValue = str | list[str]


class NoteInfo(TypedDict):
    path: str
    filename: str
    short_name: str
    path_str: str
    title: str
    tags: list[TagValue]
    title_keywords: list[str]
    tag_keywords: list[str]


class CliArgs(argparse.Namespace):
    vault: str = ""
    output: str = ""
    papers_dir: str = ""


def normalize_title(value: object, fallback: str) -> str:
    if isinstance(value, str) and value:
        return value
    return fallback


def normalize_tags(value: object) -> list[TagValue]:
    if not isinstance(value, list):
        return []

    normalized: list[TagValue] = []
    items = cast(list[object], value)
    for item_obj in items:
        if isinstance(item_obj, str):
            normalized.append(item_obj)
        elif isinstance(item_obj, list):
            string_items: list[str] = []
            nested_items = cast(list[object], item_obj)
            for sub_item_obj in nested_items:
                if isinstance(sub_item_obj, str):
                    string_items.append(sub_item_obj)
            if string_items:
                normalized.append(string_items)

    return normalized


def parse_frontmatter(content: str) -> FrontmatterData:
    """
    解析 frontmatter (YAML 格式)

    Args:
        content: markdown 文件内容

    Returns:
        frontmatter 字典
    """
    # 查找 frontmatter 开始和结束标记
    frontmatch = re.match(r'^---\s*\n(.*?)^---\s*\n', content, re.MULTILINE | re.DOTALL)

    if not frontmatch:
        return {}

    try:
        frontmatter_str = frontmatch.group(1)
        frontmatter_data = cast(object, yaml.safe_load(frontmatter_str))
        if isinstance(frontmatter_data, dict):
            normalized: FrontmatterData = {}
            frontmatter_items = cast(dict[object, object], frontmatter_data)
            for key, value in frontmatter_items.items():
                normalized[str(key)] = value
            return normalized
        return {}
    except Exception as e:
        logger.warning("Error parsing frontmatter: %s", e)
        return {}


def extract_keywords_from_title(title: str) -> list[str]:
    """
    从标题中提取关键词

    Args:
        title: 论文标题

    Returns:
        关键词列表
    """
    if not title:
        return []

    keywords: list[str] = []

    # 主要策略：提取论文的缩写或专有名词（大写开头的词）
    # 例如：从 "BLIP: Bootstrapping..." 提取 "BLIP"
    main_keyword = re.match(r'^([A-Z]{2,})(?:\s*:|\s+)', title)
    if main_keyword:
        keywords.append(main_keyword.group(1))

    # 策略2：提取冒号前的完整标题（如果是缩写+冒号格式）
    colon_match = title.split(':')
    if len(colon_match) >= 2 and len(colon_match[0].strip()) > 2:
        before_colon = colon_match[0].strip()
        # 只添加长度在3-20之间的
        if 3 <= len(before_colon) <= 20:
            keywords.append(before_colon)

    # 策略3：提取带连字符的术语（如 Vision-Language, Fine-Tuning, In-Context）
    # 只匹配明确的技术术语，避免过度分割
    tech_terms: list[str] = re.findall(r'\b[A-Z][a-z]*(?:-[A-Z][a-z]*)+\b', title)
    for term in tech_terms:
        term_clean = term.strip()
        # 只添加长度在3-20之间的技术术语
        if 3 <= len(term_clean) <= 20:
            # 过滤掉通用词
            if term_clean.lower() not in COMMON_WORDS:
                keywords.append(term_clean)

    # 去重
    return list(dict.fromkeys(keywords))


def scan_notes_directory(papers_dir: Path) -> list[NoteInfo]:
    """
    扫描 Papers 目录下的所有笔记

    Args:
        papers_dir: Papers 目录路径

    Returns:
        笔记列表
    """
    notes: list[NoteInfo] = []

    # 递归查找所有 .md 文件
    for md_file in papers_dir.rglob('*.md'):
        try:
            if 'images' in md_file.parts and md_file.name == 'index.md':
                continue

            with open(md_file, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()

            # 解析 frontmatter
            frontmatter = parse_frontmatter(content)
            title = normalize_title(frontmatter.get('title'), md_file.stem)
            tags = normalize_tags(frontmatter.get('tags'))

            # 提取信息
            # 计算相对于vault的路径（使用正斜杠）
            rel_path = md_file.relative_to(papers_dir.parent.parent)
            note_info: NoteInfo = {
                'path': str(rel_path).replace('\\', '/'),  # 使用正斜杠
                'filename': md_file.name,
                'short_name': md_file.stem,  # 文件名（不含.md扩展名），用于短链接
                'path_str': str(rel_path),  # 添加路径的字符串表示，用于正确编码
                'title': title,
                'tags': tags,
                'title_keywords': [],
                'tag_keywords': [],
            }

            # 从标题提取关键词
            title_keywords = extract_keywords_from_title(note_info['title'])
            note_info['title_keywords'] = title_keywords

            # 从 tags 提取关键词（保留有意义的tag）
            tag_keywords: list[str] = []
            for tag in note_info['tags']:
                if isinstance(tag, list):
                    for sub_tag in tag:
                        if 3 <= len(sub_tag) <= 20 and sub_tag.lower() not in COMMON_WORDS:
                            tag_keywords.append(sub_tag)
                else:
                    if 3 <= len(tag) <= 20 and tag.lower() not in COMMON_WORDS:
                        tag_keywords.append(tag)

            note_info['tag_keywords'] = tag_keywords

            notes.append(note_info)

        except Exception as e:
            logger.warning("Error reading %s: %s", md_file, e)
            continue

    return notes


def build_keyword_index(notes: list[NoteInfo]) -> dict[str, list[str]]:
    """
    构建关键词到笔记路径的映射表

    Args:
        notes: 笔记列表

    Returns:
        关键词映射字典
    """
    # 使用 set 进行去重，避免 O(n) 的 list in 操作
    keyword_sets: dict[str, set[str]] = {}

    def _add_keyword(keyword_lower: str, path: str) -> None:
        if 3 <= len(keyword_lower) <= 30 and keyword_lower not in COMMON_WORDS:
            if keyword_lower not in keyword_sets:
                keyword_sets[keyword_lower] = set()
            keyword_sets[keyword_lower].add(path)

    for note in notes:
        # Only use title-extracted keywords (acronyms, model names) — NOT tags.
        # Tags are organizational labels that appear across many papers (e.g. "evaluation",
        # "faithfulness", "LLM") and must not be linked to a specific paper path.
        for keyword in note['title_keywords']:
            _add_keyword(keyword.lower(), note['path'])

        # 使用短名称（文件名）作为关键词，但只添加主要部分
        if 'short_name' in note:
            short_name = note['short_name']
            # 移除版本号和常见后缀
            clean_short = re.sub(r'(-\d{4}\.\d{4,5}|-v\d+)$', '', short_name)

            # 如果清理后的短名称长度合适，添加到索引
            if 3 <= len(clean_short) <= 40 and clean_short.lower() not in COMMON_WORDS:
                _add_keyword(clean_short.lower(), note['path'])

    # 将 set 转换为 list 输出
    return {k: list(v) for k, v in keyword_sets.items()}


def main() -> int:
    """主函数"""
    parser = argparse.ArgumentParser(description='Scan existing notes and build keyword index')
    _ = parser.add_argument('--vault', type=str,
                            default=os.environ.get('OBSIDIAN_VAULT_PATH', ''),
                            help='Path to Obsidian vault (or set OBSIDIAN_VAULT_PATH env var)')
    _ = parser.add_argument('--output', type=str, default='existing_notes_index.json',
                            help='Output JSON file path')
    _ = parser.add_argument('--papers-dir', type=str,
                            default='20_Research/Papers',
                            help='Relative path to Papers directory')

    args = cast(CliArgs, parser.parse_args())

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%H:%M:%S',
        stream=sys.stderr,
    )

    if not args.vault:
        logger.error("未指定 vault 路径。请通过 --vault 参数或 OBSIDIAN_VAULT_PATH 环境变量设置。")
        return 1

    vault_path = Path(args.vault)
    papers_dir = vault_path / args.papers_dir

    if not papers_dir.exists():
        logger.error("Papers directory not found: %s", papers_dir)
        logger.error("Using vault path: %s", vault_path)
        return 1

    logger.info("Scanning notes in: %s", papers_dir)

    notes = scan_notes_directory(papers_dir)
    logger.info("Found %d notes", len(notes))

    keyword_index = build_keyword_index(notes)
    logger.info("Built index with %d keywords", len(keyword_index))

    # 准备输出
    output: dict[str, object] = {
        'notes': notes,
        'keyword_to_notes': keyword_index
    }

    # 保存结果
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)

    logger.info("Index saved to: %s", args.output)

    logger.info("=== Keyword Index Statistics ===")
    logger.info("Total notes: %d", len(notes))
    logger.info("Total keywords: %d", len(keyword_index))

    if len(keyword_index) > 0:
        logger.info("=== Sample Keywords ===")
        sample_keywords = sorted(keyword_index.items())[:10]
        for keyword, paths in sample_keywords:
            logger.info("  %s: %d notes", keyword, len(paths))

    return 0


if __name__ == '__main__':
    sys.exit(main())
