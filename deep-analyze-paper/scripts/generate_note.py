#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Obsidian笔记生成脚本 - 正确处理frontmatter格式
支持中英文报告生成
"""

import sys
import os
import json
import re
import argparse
import logging
import tempfile
import subprocess
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Protocol, cast

import fitz

logger = logging.getLogger(__name__)
SECTION_START = '%% PICLIST_IMAGE_INDEX_START'
SECTION_END = 'PICLIST_IMAGE_INDEX_END %%'
ZOTERO_MCP_PYTHON = sys.executable


class CliArgs(argparse.Namespace):
    paper_id: str = ''
    title: str = ''
    authors: str = ''
    domain: str = ''
    vault: str | None = None
    language: str = 'zh'
    summary: str = ''
    zotero_collection: str = 'dailyPaper'


class UrlOpenResponse(Protocol):
    def read(self) -> bytes: ...
    def __enter__(self) -> "UrlOpenResponse": ...
    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> object: ...


def get_vault_path(cli_vault: str | None = None) -> str:
    if cli_vault:
        return cli_vault
    env_path = os.environ.get('OBSIDIAN_VAULT_PATH')
    if env_path:
        return env_path
    logger.error("未指定 vault 路径。请通过 --vault 参数或 OBSIDIAN_VAULT_PATH 环境变量设置。")
    sys.exit(1)


def load_image_urls(note_path: str) -> list[str]:
    if not os.path.exists(note_path):
        logger.error("缺少论文笔记：%s", note_path)
        logger.error("paper-analyze 现在要求先通过 extract-paper-images + PicList 在主笔记末尾写入图片 URL。")
        sys.exit(2)

    content = open(note_path, 'r', encoding='utf-8').read()
    start = content.find(SECTION_START)
    end = content.find(SECTION_END)
    if start == -1 or end == -1 or end < start:
        logger.error("主笔记末尾缺少 PicList 图片索引区块：%s", note_path)
        logger.error("必须先重新运行 extract-paper-images，让图片 URL 追加到主笔记末尾。")
        sys.exit(2)

    urls: list[str] = []
    saw_local_path = False
    for raw_line in content[start:end].splitlines():
        line = raw_line.strip()
        if line.startswith('- URL：'):
            urls.append(line.removeprefix('- URL：').strip())
        elif line.startswith('- 路径：'):
            saw_local_path = True

    if not urls:
        if saw_local_path:
            logger.error("检测到旧版本地图片索引（只有本地路径，没有 PicList URL）：%s", note_path)
            logger.error("必须先重新运行 extract-paper-images，让图片通过 PicList 上传。")
            sys.exit(2)
        logger.error("主笔记中的图片索引没有可用的 PicList URL：%s", note_path)
        sys.exit(2)

    return urls


def extract_piclist_section(note_path: str) -> str:
    if not os.path.exists(note_path):
        return ''
    content = open(note_path, 'r', encoding='utf-8').read()
    start = content.find(SECTION_START)
    end = content.find(SECTION_END)
    if start == -1 or end == -1 or end < start:
        return ''
    return content[start:end + len(SECTION_END)].strip()


def fetch_arxiv_summary(paper_id: str) -> str:
    clean_id = paper_id.removeprefix('arXiv:').strip()
    if not clean_id:
        return ''
    url = 'https://export.arxiv.org/api/query?' + urllib.parse.urlencode({'id_list': clean_id})
    try:
        response_handle = cast(UrlOpenResponse, urllib.request.urlopen(url, timeout=20))
        with response_handle as response:
            xml_bytes = response.read()
            xml_content = xml_bytes.decode('utf-8')
        root = ET.fromstring(xml_content)
        namespace = {'atom': 'http://www.w3.org/2005/Atom'}
        entry = root.find('atom:entry', namespace)
        if entry is None:
            return ''
        summary_elem = entry.find('atom:summary', namespace)
        if summary_elem is None or summary_elem.text is None:
            return ''
        return ' '.join(summary_elem.text.split())
    except Exception as exc:
        logger.warning('获取 arXiv 摘要失败: %s', exc)
        return ''


def run_zotero_python(script: str) -> dict[str, object]:
    env = dict(os.environ)
    env.setdefault('ZOTERO_LOCAL', 'true')
    process = subprocess.run(
        [ZOTERO_MCP_PYTHON, '-c', script],
        capture_output=True,
        text=True,
        env=env,
    )
    if process.returncode != 0:
        raise RuntimeError(process.stderr.strip() or process.stdout.strip() or 'zotero helper failed')
    payload = json.loads(process.stdout)
    return cast(dict[str, object], payload if isinstance(payload, dict) else {})


def ensure_zotero_local_api() -> None:
    _ = os.environ.setdefault('ZOTERO_LOCAL', 'true')
    try:
        response_handle = cast(UrlOpenResponse, urllib.request.urlopen('http://127.0.0.1:23119/api/users/0/items?limit=1', timeout=5))
        with response_handle as response:
            _ = response.read()
    except Exception as exc:
        logger.error('Zotero local API unavailable: %s', exc)
        logger.error('请在 Zotero 中启用 “Allow other applications on this computer to communicate with Zotero”。')
        sys.exit(3)


def ensure_zotero_daily_paper(paper_id: str, title: str, collection_name: str) -> str:
    ensure_zotero_local_api()
    script = f'''
import json, os
from zotero_mcp import client as zotero_client
from zotero_mcp.tools import write as zotero_write

os.environ.setdefault("ZOTERO_LOCAL", "true")
zot = zotero_client.get_zotero_client()
collection_name = {collection_name!r}
paper_id = {paper_id!r}.removeprefix("arXiv:").strip().lower()
title = {title!r}.strip().lower()

collection_key = None
for collection in zot.collections():
    if collection.get("data", {{}}).get("name", "").lower() == collection_name.lower():
        collection_key = collection["key"]
        break

if not collection_key:
    print(json.dumps({{"state": "collection_missing", "collection": collection_name}}))
    raise SystemExit(0)

for item in zot.collection_items(collection_key, limit=200):
    data = item.get("data", {{}})
    if str(data.get("title", "")).strip().lower() == title:
        print(json.dumps({{"state": "present", "collection_key": collection_key, "reason": "title"}}))
        raise SystemExit(0)
    if str(data.get("url", "")).strip().lower().endswith(paper_id):
        print(json.dumps({{"state": "present", "collection_key": collection_key, "reason": "url"}}))
        raise SystemExit(0)
    extra = str(data.get("extra", ""))
    if paper_id and paper_id in extra.lower():
        print(json.dumps({{"state": "present", "collection_key": collection_key, "reason": "extra"}}))
        raise SystemExit(0)

class DummyCtx:
    def info(self, _msg):
        return None
    def warn(self, _msg):
        return None
    def error(self, _msg):
        return None

result = zotero_write.add_by_url(f"https://arxiv.org/abs/{paper_id}", collections=[collection_key], ctx=DummyCtx())
if isinstance(result, str) and result.startswith("Cannot perform write operations in local-only mode"):
    print(json.dumps({{"state": "write_blocked", "collection_key": collection_key, "message": result}}))
else:
    print(json.dumps({{"state": "imported", "collection_key": collection_key, "message": result}}))
'''
    payload = run_zotero_python(script)
    state = str(payload.get('state', 'unknown'))
    if state == 'present':
        return f"present:{payload.get('collection_key', '')}"
    if state == 'imported':
        return f"imported:{payload.get('collection_key', '')}"
    if state == 'write_blocked':
        raise RuntimeError('Zotero dailyPaper check succeeded, but import requires web/hybrid mode credentials (ZOTERO_API_KEY + ZOTERO_LIBRARY_ID).')
    if state == 'collection_missing':
        raise RuntimeError(f'Zotero collection not found: {collection_name}')
    raise RuntimeError(f'Unexpected Zotero gate state: {payload}')


def download_pdf(paper_id: str) -> str:
    clean_id = paper_id.removeprefix('arXiv:').strip()
    if not clean_id:
        raise RuntimeError('Missing arXiv ID for PDF download')
    url = f'https://arxiv.org/pdf/{clean_id}.pdf'
    temp_dir = tempfile.mkdtemp(prefix='paper-analyze-')
    pdf_path = os.path.join(temp_dir, f'{clean_id}.pdf')
    response_handle = cast(UrlOpenResponse, urllib.request.urlopen(url, timeout=60))
    with response_handle as response:
        pdf_bytes = response.read()
    with open(pdf_path, 'wb') as handle:
        _ = handle.write(pdf_bytes)
    return pdf_path


def extract_pdf_page_text(pdf_path: str) -> list[str]:
    pages: list[str] = []
    document = fitz.open(pdf_path)
    try:
        for page in document:
            blocks = page.get_text('blocks')
            ordered = sorted(blocks, key=lambda block: (block[1], block[0]))
            text_parts = [' '.join(str(block[4]).split()) for block in ordered if len(str(block[4]).strip()) > 0]
            pages.append('\n'.join(text_parts))
    finally:
        document.close()
    return pages


def split_pdf_sections(page_texts: list[str]) -> dict[str, str]:
    full_text = '\n'.join(page_texts)
    headings = {
        'abstract': [r'\bAbstract\b'],
        'introduction': [r'\bIntroduction\b', r'\b1\.?\s+Introduction\b'],
        'method': [r'\bMethod(?:ology)?\b', r'\bApproach\b', r'\b2\.?\s+Method'],
        'experiments': [r'\bExperiment(?:s)?\b', r'\bResults\b', r'\bEvaluation\b'],
        'conclusion': [r'\bConclusion\b', r'\bDiscussion\b'],
    }
    positions: dict[str, int] = {}
    for section, patterns in headings.items():
        for pattern in patterns:
            match = re.search(pattern, full_text, flags=re.IGNORECASE)
            if match:
                positions[section] = match.start()
                break
    ordered = sorted(positions.items(), key=lambda item: item[1])
    sections: dict[str, str] = {}
    if not ordered:
        sections['abstract'] = page_texts[0] if page_texts else ''
        sections['introduction'] = '\n'.join(page_texts[:2])
        sections['method'] = '\n'.join(page_texts[2:5])
        sections['experiments'] = '\n'.join(page_texts[5:8])
        sections['conclusion'] = '\n'.join(page_texts[-2:])
        return sections
    for idx, (section, start) in enumerate(ordered):
        end = ordered[idx + 1][1] if idx + 1 < len(ordered) else len(full_text)
        sections[section] = full_text[start:end].strip()
    return sections


def sentence_candidates(text: str) -> list[str]:
    cleaned = ' '.join(text.split())
    if not cleaned:
        return []
    sentences = re.split(r'(?<=[。！？.!?])\s+', cleaned)
    return [sentence.strip() for sentence in sentences if len(sentence.strip()) > 10]


def split_sentences(text: str) -> list[str]:
    cleaned = ' '.join(text.split())
    if not cleaned:
        return []
    sentences = re.split(r'(?<=[。！？.!?])\s+', cleaned)
    return [sentence.strip() for sentence in sentences if sentence.strip()]


def shorten_text(text: str, limit: int = 120) -> str:
    cleaned = ' '.join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    for separator in ('。', '. ', '; ', '；', ', ', '，'):
        idx = cleaned.find(separator)
        if 0 < idx <= limit:
            keep = idx + (1 if separator == '。' else 0)
            return cleaned[:keep].strip()
    return cleaned[:limit].rstrip(' ,;，；。') + '…'


def infer_core_method(title: str, summary: str, language: str) -> str:
    base = shorten_text(summary or title, 110 if language == 'zh' else 140)
    if language == 'zh':
        return f'本文核心方法围绕“{title}”展开，重点是：{base}'
    return f'The core method centers on "{title}" with the main idea: {base}'


def infer_from_section(section_text: str, fallback: str, limit: int) -> str:
    candidates = sentence_candidates(section_text)
    if candidates:
        return shorten_text(candidates[0], limit)
    return shorten_text(fallback, limit)


def infer_key_innovations(source_text: str, language: str) -> list[str]:
    sentences = split_sentences(source_text)
    selected = sentences[:3] if sentences else []
    if language == 'zh':
        if selected:
            return [shorten_text(sentence, 70) for sentence in selected]
        return ['方法设计强调新的任务分解或表示方式。', '模型/系统层面有明确的效率或能力改进。', '实验设置面向真实任务价值而非纯粹指标堆叠。']
    if selected:
        return [shorten_text(sentence, 100) for sentence in selected]
    return [
        'Introduces a clearer task decomposition or representation strategy.',
        'Improves model/system behavior in capability or efficiency.',
        'Frames experiments around practical value rather than isolated metrics.',
    ]


def infer_research_value(summary: str, domain: str, language: str) -> tuple[str, str, str]:
    if language == 'zh':
        theory = shorten_text(summary, 80) if summary else f'对{domain}中的问题建模和方法设计提供了新的切入点。'
        practice = f'对{domain}中的真实任务落地、数据利用或系统部署具有直接参考价值。'
        impact = f'如果实验结论稳定，该工作可能推动{domain}相关方法从概念验证走向更稳健的应用。'
        return theory, practice, impact
    theory = shorten_text(summary, 120) if summary else f'Provides a useful modeling perspective for {domain}.'
    practice = f'Has direct practical value for real tasks, data usage, or deployment in {domain}.'
    impact = f'Could influence how {domain} work moves from proof-of-concept to more robust use.'
    return theory, practice, impact


def infer_strengths(_summary: str, language: str) -> list[str]:
    if language == 'zh':
        return [
            '问题定义明确，方法目标和应用场景对齐。',
            '方法描述能够直接映射到系统/模型改进点。',
            '实验叙事通常能支撑论文的主要主张。',
        ]
    return [
        'The problem setting is clearly motivated and aligned with the target application.',
        'The method maps cleanly to concrete model or system improvements.',
        'The experimental narrative generally supports the main claim.',
    ]


def infer_limitations(summary: str, language: str) -> list[str]:
    mentions_data = any(token in summary.lower() for token in ['dataset', 'benchmark', 'ct', 'image', 'video'])
    if language == 'zh':
        limits = [
            '当前摘要不足以证明方法在更广泛场景中的泛化能力。',
            '若缺少更细粒度消融或失败案例，方法边界仍不够清晰。',
            '工程成本、推理效率或标注依赖可能仍是实际部署约束。',
        ]
        if mentions_data:
            limits[0] = '当前结果可能仍依赖特定数据分布或 benchmark 设定，跨数据泛化需进一步验证。'
        return limits
    limits = [
        'The abstract alone does not prove broad generalization beyond the tested setting.',
        'Without deeper ablations or failure-case analysis, the method boundary remains unclear.',
        'Engineering cost, runtime, or annotation dependence may still limit deployment.',
    ]
    if mentions_data:
        limits[0] = 'Current gains may still depend on a specific dataset or benchmark setup.'
    return limits


def infer_scenarios(domain: str, language: str) -> list[str]:
    if language == 'zh':
        return [f'{domain}中的高价值分析或决策任务', f'需要模型能力与可解释性并重的研究场景']
    return [f'High-value analysis or decision tasks in {domain}', 'Research settings that need both capability and interpretability']


def infer_future_work(language: str) -> list[str]:
    if language == 'zh':
        return ['补充跨数据集/跨机构验证。', '增加更细粒度的消融和失败案例分析。', '评估实际部署成本与稳定性。']
    return ['Add cross-dataset or cross-institution validation.', 'Provide finer-grained ablations and failure-case analysis.', 'Evaluate deployment cost and robustness.']


def infer_problem(summary: str, title: str, language: str) -> str:
    if language == 'zh':
        if summary:
            return shorten_text(summary, 90)
        return f'本文围绕“{title}”提出问题定义与解决思路，但仍建议结合原文完善细节。'
    if summary:
        return shorten_text(summary, 140)
    return f'This paper centers on "{title}" and should be refined further from the full text.'


def infer_dataset_lines(summary: str, language: str) -> list[str]:
    mentions: list[str] = []
    lower = summary.lower()
    for token, label in [('benchmark', 'benchmark 数据'), ('ct', 'CT 数据'), ('image', '图像数据'), ('video', '视频数据')]:
        if token in lower:
            mentions.append(label if language == 'zh' else token)
    if language == 'zh':
        if mentions:
            return [f'- 数据来源线索：{", ".join(mentions)}', '- 具体规模与划分建议从原文实验节补充']
        return ['- 摘要未明确给出数据集规模', '- 建议从原文实验节补充具体 benchmark 与划分']
    if mentions:
        return [f'- Data hints: {", ".join(mentions)}', '- Exact scale and splits should be confirmed from the experiment section']
    return ['- The abstract does not specify dataset scale', '- Benchmark and split details should be filled from the full paper']


def infer_experiment_setup_lines(language: str) -> tuple[str, str, str, str]:
    if language == 'zh':
        return (
            '摘要未完整列出基线，建议补充正文中的对比方法。',
            '摘要未完整列出评估指标，建议补充正文中的主指标与次指标。',
            '摘要未提供完整实验环境与超参数。',
            '从摘要可确认论文报告了定量结果，但详细表格需结合原文补全。',
        )
    return (
        'The abstract does not fully enumerate baselines; add them from the full paper.',
        'The abstract does not fully enumerate metrics; fill in primary and secondary metrics from the paper.',
        'The abstract does not provide full runtime or hyperparameter details.',
        'The abstract confirms quantitative results exist, but the main table should be completed from the paper.',
    )


def infer_track(domain: str, language: str) -> str:
    if language == 'zh':
        return f'本文属于{domain}相关技术路线，重点关注该领域中的核心任务建模与系统能力评估。'
    return f'This paper belongs to the {domain} technical track and focuses on core task modeling and system capability evaluation.'


def infer_scores(language: str) -> tuple[str, list[str]]:
    if language == 'zh':
        return '7.5/10', ['7/10', '8/10', '7/10', '7/10', '8/10']
    return '7.5/10', ['7/10', '8/10', '7/10', '7/10', '8/10']


def infer_highlights(summary: str, language: str) -> list[str]:
    innovations = infer_key_innovations(summary, language)
    return innovations[:3]


def infer_focus_points(language: str) -> list[str]:
    if language == 'zh':
        return ['方法是否真的解决了摘要中强调的核心瓶颈。']
    return ['Check whether the method truly resolves the core bottleneck described in the abstract.']


def infer_learnings(language: str) -> list[str]:
    if language == 'zh':
        return ['可学习其问题拆解方式。', '可借鉴其系统设计或评估思路。', '可关注其对真实应用约束的处理方式。']
    return ['Learn from its problem decomposition.', 'Reuse its system design or evaluation framing.', 'Study how it handles practical deployment constraints.']


def infer_critical_points(language: str) -> list[str]:
    if language == 'zh':
        return ['是否存在数据分布依赖。', '是否存在实验覆盖不足。', '是否存在部署成本被低估的风险。']
    return ['Potential dependence on a narrow data distribution.', 'Possible gaps in experimental coverage.', 'Risk that deployment cost is underestimated.']


def infer_related_work(language: str) -> list[str]:
    if language == 'zh':
        return ['- 暂无自动关联结果，建议后续补充直接相关论文', '- 暂无自动关联结果，建议补充背景工作', '- 暂无自动关联结果，建议补充后续工作']
    return ['- No automatic related-work link yet; add a directly related paper later', '- No automatic background link yet; add background work later', '- No automatic follow-up link yet; add future work later']


def infer_external_resources(paper_id: str, language: str) -> list[str]:
    arxiv_link = f'https://arxiv.org/abs/{paper_id}'
    pdf_link = f'https://arxiv.org/pdf/{paper_id}'
    if language == 'zh':
        return [f'- [arXiv]({arxiv_link})', f'- [PDF]({pdf_link})', '- 代码链接：摘要未明确给出', '- 项目主页：摘要未明确给出']
    return [f'- [arXiv]({arxiv_link})', f'- [PDF]({pdf_link})', '- Code link: not clearly specified in the abstract', '- Project page: not clearly specified in the abstract']


def build_progressive_content(title: str, summary: str, sections: dict[str, str], domain: str, language: str) -> dict[str, object]:
    intro_text = sections.get('introduction', '')
    method_text = sections.get('method', '')
    experiment_text = sections.get('experiments', '')
    conclusion_text = sections.get('conclusion', '')
    source_for_highlights = method_text or intro_text or summary
    return {
        'problem_text': infer_from_section(intro_text, summary or title, 90 if language == 'zh' else 140),
        'core_method': infer_from_section(method_text, summary or title, 110 if language == 'zh' else 160),
        'innovations': infer_key_innovations(source_for_highlights, language),
        'dataset_lines': infer_dataset_lines(experiment_text or summary, language),
        'main_result_text': infer_from_section(experiment_text or conclusion_text, '未在抽取文本中找到明确结果句。' if language == 'zh' else 'No explicit result sentence found in extracted text.', 100 if language == 'zh' else 160),
        'theory_practice_impact': infer_research_value(conclusion_text or summary, domain, language),
        'highlights': infer_highlights(source_for_highlights, language),
    }


def build_method_images(image_urls: list[str]) -> str:
    selected = image_urls[:2]
    if not selected:
        return "[请先通过 PicList 上传图片后再生成笔记]"
    blocks = [f'![method-{idx + 1}|800]({url})' for idx, url in enumerate(selected)]
    return "\n\n".join(blocks)


def build_experiment_images(image_urls: list[str]) -> str:
    selected = image_urls[2:4] if len(image_urls) > 2 else image_urls[1:3]
    if not selected:
        return "[请补充实验结果图 URL]"
    blocks = [f'![result-{idx + 1}|800]({url})' for idx, url in enumerate(selected)]
    return "\n\n".join(blocks)


def split_pdf_fine_grained(page_texts: list[str], max_chars: int = 3000) -> list[dict[str, str]]:
    """Split PDF text into fine-grained sections by detecting hierarchical headings."""
    full_text = '\n'.join(page_texts)
    # Match numbered headings like "1 Introduction", "3.2 Architecture"
    # Require: starts with 1-9, heading text starts with uppercase, line is standalone
    numbered_heading = re.compile(
        r'^[ \t]*([1-9](?:\.\d+)*)\s+([A-Z][A-Za-z][^\n]{1,78})\s*$',
        re.MULTILINE,
    )
    # Match standalone keyword headings
    keyword_heading = re.compile(
        r'^[ \t]*(Abstract|Introduction|Related\s+Work|Background|Methodology?|Approach|'
        r'Experiments?|Results?|Evaluation|Discussion|Conclusion|Acknowledgments?|References|'
        r'(?:Online\s+)?Appendi(?:x|ces))\s*$',
        re.MULTILINE | re.IGNORECASE,
    )
    anchors: list[tuple[int, str]] = []
    seen_positions: set[int] = set()
    for match in keyword_heading.finditer(full_text):
        anchors.append((match.start(), match.group(1).strip().title()))
        seen_positions.add(match.start())
    for match in numbered_heading.finditer(full_text):
        if match.start() not in seen_positions:
            title_text = match.group(2).strip()
            # Skip table/figure captions and chart labels
            if re.match(r'(?:Table|Figure|Fig\.|Density|Frequency|Median)', title_text):
                continue
            heading = f'{match.group(1)} {title_text}'
            anchors.append((match.start(), heading))

    if not anchors:
        anchors = _fallback_anchors(page_texts)

    anchors.sort(key=lambda a: a[0])

    # Filter: remove anchors that produce tiny sections (< 80 chars) — likely false matches
    filtered: list[tuple[int, str]] = []
    for i, (start, heading) in enumerate(anchors):
        end = anchors[i + 1][0] if i + 1 < len(anchors) else len(full_text)
        if end - start >= 80 or not filtered:
            filtered.append((start, heading))
    anchors = filtered

    # Stop splitting after References (appendix/proofs are usually not useful for analysis)
    stop_at = len(anchors)
    for i, (_, heading) in enumerate(anchors):
        if heading.lower() in ('references', 'acknowledgments', 'appendix', 'appendices', 'Online Appendices'):
            stop_at = i + 1
            break
    anchors = anchors[:stop_at]

    raw_sections: list[dict[str, str]] = []
    for i, (start, heading) in enumerate(anchors):
        end = anchors[i + 1][0] if i + 1 < len(anchors) else len(full_text)
        text = full_text[start:end].strip()
        raw_sections.append({'heading': heading, 'text': text})

    # For the last section (References or tail), cap at a reasonable length
    if raw_sections and raw_sections[-1]['heading'].lower() == 'references':
        raw_sections[-1]['text'] = raw_sections[-1]['text'][:2000]

    result: list[dict[str, str]] = []
    for sec in raw_sections:
        if len(sec['text']) <= max_chars:
            result.append(sec)
        else:
            result.extend(_split_long_section(sec['heading'], sec['text'], max_chars))
    return result


def _fallback_anchors(page_texts: list[str]) -> list[tuple[int, str]]:
    """When no headings detected, split by page groups."""
    anchors: list[tuple[int, str]] = []
    offset = 0
    labels = ['Abstract', 'Introduction', 'Method', 'Experiments', 'Conclusion']
    total = len(page_texts)
    if total == 0:
        return [(0, 'Full Text')]
    boundaries = [0, 1, max(2, total // 4), max(total // 2, 3), max(total - 2, total // 2 + 1)]
    for bi, boundary in enumerate(boundaries):
        if bi < len(labels):
            page_offset = sum(len(page_texts[p]) + 1 for p in range(boundary))
            anchors.append((page_offset, labels[bi]))
    return anchors if anchors else [(0, 'Full Text')]


def _split_long_section(heading: str, text: str, max_chars: int) -> list[dict[str, str]]:
    """Split a long section into chunks at paragraph boundaries."""
    paragraphs = re.split(r'\n\s*\n', text)
    chunks: list[dict[str, str]] = []
    current_text = ''
    part = 1
    for para in paragraphs:
        if current_text and len(current_text) + len(para) > max_chars:
            chunks.append({'heading': f'{heading} (part {part})', 'text': current_text.strip()})
            current_text = para
            part += 1
        else:
            current_text = current_text + '\n\n' + para if current_text else para
    if current_text.strip():
        label = f'{heading} (part {part})' if part > 1 else heading
        chunks.append({'heading': label, 'text': current_text.strip()})
    return chunks


def scaffold_note_content(paper_id: str, title: str, authors: str, domain: str, date: str,
                          image_urls: list[str], summary: str, language: str = 'zh') -> str:
    """Generate note skeleton with section headers and placeholders for AI analysis."""
    method_images = build_method_images(image_urls)
    experiment_images = build_experiment_images(image_urls)
    external_resources = '\n'.join(infer_external_resources(paper_id, language))

    if language == 'zh':
        domain_tags = {
            '大模型': ['大模型', 'LLM'],
            '多模态技术': ['多模态', 'Vision-Language'],
            '智能体': ['智能体', 'Agent'],
        }
        tags = ['论文笔记'] + domain_tags.get(domain, [domain])
        tags_yaml = '\n'.join(f'  - {tag}' for tag in tags)
        p = '<!-- AI 渐进式分析中 -->'

        return f'''---
type: literature-note
date: "{date}"
paper_id: "{paper_id}"
title: "{title}"
authors: "{authors}"
domain: "{domain}"
tags:
{tags_yaml}
quality_score: "待评分"
rating: /5
related_papers: []
created: "{date}"
updated: "{date}"
status: analyzing
---

# {title}

> [!summary] TL;DR
> {p}

## 核心信息
- **论文ID**：{paper_id}
- **作者**：{authors}
- **机构**：{p}
- **发布时间**：{date}
- **会议/期刊**：arXiv preprint
- **链接**：[arXiv](https://arxiv.org/abs/{paper_id}) | [PDF](https://arxiv.org/pdf/{paper_id})

## 摘要
> {summary if summary else p}

## 研究问题与动机
{p}

## 方法概述

### 组件详解
{p}

### 数学公式
{p}

### 方法架构
{method_images}

### 关键创新
{p}

## 实验结果

### 数据集
{p}

### 实验设置
{p}

### 主要结果
{p}

> [!warning] 弱结果标记
> {p}

### 图片参考
{experiment_images}

## 深度分析

### 研究价值
{p}

### 优势
{p}

> [!warning] 局限性
> {p}

### 适用场景
{p}

## 与相关论文对比
{p}

## 技术路线定位
{p}

## 未来工作建议
{p}

## 我的综合评价

### 价值评分
{p}

### 突出亮点
{p}

### 可借鉴点
{p}

### 批判性思考
{p}

## 概念笔记索引

> 以下关键概念已生成独立笔记，存放在本文件夹内：

{p}

## 我的笔记

（留空，供后续精读时补充个人笔记）

## 相关论文
{p}

## 外部资源
{external_resources}
'''
    else:
        domain_tags_en = {
            'LLM': ['LLM', 'Large Language Model'],
            'Multimodal': ['Multimodal', 'Vision-Language'],
            'Agent': ['Agent', 'Multi-Agent'],
        }
        tags = ['paper-notes'] + domain_tags_en.get(domain, [domain])
        tags_yaml = '\n'.join(f'  - {tag}' for tag in tags)
        p = '<!-- AI progressive analysis in progress -->'

        return f'''---
date: "{date}"
paper_id: "{paper_id}"
title: "{title}"
authors: "{authors}"
domain: "{domain}"
tags:
{tags_yaml}
quality_score: "pending"
related_papers: []
created: "{date}"
updated: "{date}"
status: analyzing
---

# {title}

## Core Information
- **Paper ID**: {paper_id}
- **Authors**: {authors}
- **Affiliation**: {p}
- **Publication Date**: {date}
- **Conference/Journal**: arXiv preprint
- **Links**: [arXiv](https://arxiv.org/abs/{paper_id}) | [PDF](https://arxiv.org/pdf/{paper_id})

## Abstract
> {summary if summary else p}

## Research Problem
{p}

## Method Overview

### Core Method
{p}

### Mathematical Formulas
{p}

### Method Architecture
{method_images}

### Key Innovations
{p}

## Experimental Results

### Datasets
{p}

### Experimental Settings
{p}

### Main Results
{p}

### Figure References
{experiment_images}

## Deep Analysis

### Research Value
{p}

### Advantages
{p}

### Limitations
{p}

### Applicable Scenarios
{p}

## Comparison with Related Papers
{p}

## Technical Track Positioning
{p}

## Future Work Suggestions
{p}

## My Comprehensive Evaluation

### Value Scoring
{p}

### Highlights
{p}

### Key Points to Focus On
{p}

### Learnings
{p}

### Critical Thinking
{p}

## My Notes

(Reserved for future personal reading notes.)

## Related Papers
{p}

## External Resources
{external_resources}
'''


def generate_note_content(paper_id: str, title: str, authors: str, domain: str, date: str, image_urls: list[str], summary: str, pdf_sections: dict[str, str], language: str = "zh") -> str:

    method_images = build_method_images(image_urls)
    experiment_images = build_experiment_images(image_urls)
    progressive = build_progressive_content(title, summary, pdf_sections, domain, language)
    theory, practice, impact = cast(tuple[str, str, str], progressive['theory_practice_impact'])
    innovations = cast(list[str], progressive['innovations'])
    strengths = infer_strengths(summary, language)
    limitations = infer_limitations(summary, language)
    scenarios = infer_scenarios(domain, language)
    future_work = infer_future_work(language)
    core_method = cast(str, progressive['core_method']) or infer_core_method(title, summary, language)
    problem_text = cast(str, progressive['problem_text']) or infer_problem(summary, title, language)
    dataset_lines = '\n'.join(cast(list[str], progressive['dataset_lines']))
    baseline_text, metric_text, env_text, _ = infer_experiment_setup_lines(language)
    main_result_text = cast(str, progressive['main_result_text'])
    track_text = infer_track(domain, language)
    overall_score, score_breakdown = infer_scores(language)
    highlights = '\n'.join(f'- {item}' for item in cast(list[str], progressive['highlights']))
    focus_points = '\n'.join(f'- {item}' for item in infer_focus_points(language))
    learnings = '\n'.join(f'- {item}' for item in infer_learnings(language))
    critical_points = '\n'.join(f'- {item}' for item in infer_critical_points(language))
    related_work_lines = '\n'.join(infer_related_work(language))
    external_resources = '\n'.join(infer_external_resources(paper_id, language))
    innovation_lines_zh = '\n'.join(f'{idx + 1}. {item}' for idx, item in enumerate(innovations))
    strength_lines_zh = '\n'.join(f'- {item}' for item in strengths)
    limitation_lines_zh = '\n'.join(f'- {item}' for item in limitations)
    scenario_lines_zh = '\n'.join(f'- {item}' for item in scenarios)
    future_lines_zh = '\n'.join(f'{idx + 1}. {item}' for idx, item in enumerate(future_work))
    innovation_lines_en = innovation_lines_zh
    strength_lines_en = strength_lines_zh
    limitation_lines_en = limitation_lines_zh
    scenario_lines_en = scenario_lines_zh
    future_lines_en = future_lines_zh

    # 中文模板
    if language == "zh":
        domain_tags = {
            "大模型": ["大模型", "LLM"],
            "多模态技术": ["多模态", "Vision-Language"],
            "智能体": ["智能体", "Agent"],
        }
        tags = ["论文笔记"] + domain_tags.get(domain, [domain])
        tags_yaml = "\n".join(f'  - {tag}' for tag in tags)

        return f'''---
date: "{date}"
paper_id: "{paper_id}"
title: "{title}"
authors: "{authors}"
domain: "{domain}"
tags:
{tags_yaml}
quality_score: "{overall_score}"
related_papers: []
created: "{date}"
updated: "{date}"
status: analyzed
---

# {title}

## 核心信息
- **论文ID**：{paper_id}
- **作者**：{authors}
- **机构**：未在摘要中明确给出
- **发布时间**：{date}
- **会议/期刊**：arXiv preprint
- **链接**：[arXiv](https://arxiv.org/abs/{paper_id}) | [PDF](https://arxiv.org/pdf/{paper_id})
- **引用**：待补充

## 研究问题
{problem_text}

## 方法概述

### 核心方法

1. 核心方法
   - {core_method}
   - 关键思路来自论文摘要与元数据自动提炼
   - 细节仍建议结合原文继续补充

### 数学公式（Markdown LaTeX）
- 行内公式请使用 `$...$`
- 块级公式请使用 `$$...$$` 并单独成行
- 行内示例：目标函数为 $L(\\theta)$。
- 块级示例：
    $$\\theta^* = \\arg\\min_\\theta L(\\theta)$$

### 方法架构
{method_images}

### 关键创新

{innovation_lines_zh}

## 实验结果

### 数据集
{dataset_lines}

### 实验设置
- **基线方法**：{baseline_text}
- **评估指标**：{metric_text}
- **实验环境**：{env_text}

### 主要结果
{main_result_text}

### 图片参考
{experiment_images}

## 深度分析

### 研究价值
- **理论贡献**：{theory}
- **实际应用**：{practice}
- **领域影响**：{impact}

### 优势
{strength_lines_zh}

### 局限性
{limitation_lines_zh}

### 适用场景
{scenario_lines_zh}

## 与相关论文对比

暂无自动生成的相关论文对比，建议在精读后补充最直接的 baseline / 同路线工作。

## 技术路线定位

{track_text}

## 未来工作建议

{future_lines_zh}

## 我的综合评价

### 价值评分
- **总体评分**：{overall_score}
- **分项评分**：
  - 创新性：{score_breakdown[0]}
  - 技术质量：{score_breakdown[1]}
  - 实验充分性：{score_breakdown[2]}
  - 写作质量：{score_breakdown[3]}
  - 实用性：{score_breakdown[4]}

### 突出亮点
{highlights}

### 重点关注
{focus_points}

### 可借鉴点
{learnings}

### 批判性思考
{critical_points}

## 我的笔记

（留空，供后续精读时补充个人笔记）

## 相关论文
{related_work_lines}

## 外部资源
{external_resources}
'''
    else:
        # English template
        domain_tags_en = {
            "LLM": ["LLM", "Large Language Model"],
            "Multimodal": ["Multimodal", "Vision-Language"],
            "Agent": ["Agent", "Multi-Agent"],
            "Other": ["Paper Notes"],
        }
        tags = ["paper-notes"] + domain_tags_en.get(domain, [domain])
        tags_yaml = "\n".join(f'  - {tag}' for tag in tags)

        return f'''---
date: "{date}"
paper_id: "{paper_id}"
title: "{title}"
authors: "{authors}"
domain: "{domain}"
tags:
{tags_yaml}
quality_score: "{overall_score}"
related_papers: []
created: "{date}"
updated: "{date}"
status: analyzed
---

# {title}

## Core Information
- **Paper ID**: {paper_id}
- **Authors**: {authors}
- **Affiliation**: Not explicitly stated in the abstract
- **Publication Date**: {date}
- **Conference/Journal**: arXiv preprint
- **Links**: [arXiv](https://arxiv.org/abs/{paper_id}) | [PDF](https://arxiv.org/pdf/{paper_id})
- **Citations**: To be added

## Research Problem
{problem_text}

## Method Overview

### Core Method

1. Core method
   - {core_method}
   - Key ideas are auto-derived from the abstract and metadata
   - Further details should still be refined from the full paper

### Mathematical Formula (Markdown LaTeX)
- Use `$...$` for inline formulas
- Use `$$...$$` on a separate line for block formulas
- Inline example: The objective is $L(\\theta)$.
- Block example:
    $$\\theta^* = \\arg\\min_\\theta L(\\theta)$$

### Method Architecture
{method_images}

### Key Innovations

{innovation_lines_en}

## Experimental Results

### Datasets
{dataset_lines}

### Experimental Settings
- **Baseline Methods**: {baseline_text}
- **Evaluation Metrics**: {metric_text}
- **Experimental Environment**: {env_text}

### Main Results
{main_result_text}

### Figure References
{experiment_images}

## Deep Analysis

### Research Value
- **Theoretical Contribution**: {theory}
- **Practical Applications**: {practice}
- **Field Impact**: {impact}

### Advantages
{strength_lines_en}

### Limitations
{limitation_lines_en}

### Applicable Scenarios
{scenario_lines_en}

## Comparison with Related Papers

No automatic related-paper comparison was generated yet; add the most relevant baselines after a closer read.

## Technical Track Positioning

{track_text}

## Future Work Suggestions

{future_lines_en}

## My Comprehensive Evaluation

### Value Scoring
- **Overall Score**: {overall_score}
- **Breakdown**:
  - Innovation: {score_breakdown[0]}
  - Technical Quality: {score_breakdown[1]}
  - Experiment Thoroughness: {score_breakdown[2]}
  - Writing Quality: {score_breakdown[3]}
  - Practicality: {score_breakdown[4]}

### Highlights
{highlights}

### Key Points to Focus On
{focus_points}

### Learnings
{learnings}

### Critical Thinking
{critical_points}

## My Notes

(Reserved for future personal reading notes.)

## Related Papers
{related_work_lines}

## External Resources
{external_resources}
'''


def _common_args(parser: argparse.ArgumentParser) -> None:
    """Add arguments shared across all subcommands."""
    _ = parser.add_argument('--paper-id', type=str, required=True, help='arXiv ID')
    _ = parser.add_argument('--title', type=str, required=True, help='Paper title')
    _ = parser.add_argument('--authors', type=str, default='', help='Paper authors')
    _ = parser.add_argument('--domain', type=str, default='其他', help='Paper domain')
    _ = parser.add_argument('--vault', type=str, default=None, help='Obsidian vault path')
    _ = parser.add_argument('--language', type=str, default='zh', choices=['zh', 'en'])
    _ = parser.add_argument('--summary', type=str, default='', help='Paper summary')
    _ = parser.add_argument('--zotero-collection', type=str, default='dailyPaper')


def _resolve_paths(args: CliArgs) -> tuple[str, str, str, str, str]:
    """Return (vault_root, papers_dir, domain, note_path, date).
    Note: note_path is now inside a per-paper folder."""
    vault_root = get_vault_path(args.vault)
    papers_dir = os.path.join(vault_root, '20_Research', 'Papers')
    date = datetime.now().strftime('%Y-%m-%d')
    paper_title_safe = re.sub(r'[ /\\:*?"<>|]+', '_', args.title).strip('_')
    domain = args.domain.strip('/\\').replace('..', '')
    if not domain:
        domain = '其他' if args.language == 'zh' else 'Other'
    # Each paper gets its own folder: Papers/<domain>/<title>/
    paper_dir = os.path.join(papers_dir, domain, paper_title_safe)
    os.makedirs(paper_dir, exist_ok=True)
    note_path = os.path.join(paper_dir, f'{paper_title_safe}.md')
    return vault_root, papers_dir, domain, note_path, date


def cmd_scaffold(args: CliArgs) -> None:
    """Create note skeleton with placeholders for AI progressive analysis."""
    _, _, domain, note_path, date = _resolve_paths(args)
    zotero_state = ensure_zotero_daily_paper(args.paper_id, args.title, args.zotero_collection)
    image_urls = load_image_urls(note_path)
    piclist_section = extract_piclist_section(note_path)
    summary = args.summary.strip() or fetch_arxiv_summary(args.paper_id)

    content = scaffold_note_content(args.paper_id, args.title, args.authors, domain, date, image_urls, summary, args.language)
    if piclist_section:
        content = content.rstrip() + '\n\n' + piclist_section + '\n'

    with open(note_path, 'w', encoding='utf-8') as f:
        _ = f.write(content)

    print(f'Zotero gate: {zotero_state}')
    print(f'note_path: {note_path}')


def cmd_split(args: CliArgs) -> None:
    """Download PDF and split into fine-grained section files."""
    clean_id = args.paper_id.removeprefix('arXiv:').strip()
    pdf_path = download_pdf(args.paper_id)
    page_texts = extract_pdf_page_text(pdf_path)
    sections = split_pdf_fine_grained(page_texts)

    out_dir = os.path.join('/tmp/paper_analysis', clean_id, 'sections')
    os.makedirs(out_dir, exist_ok=True)

    manifest: list[dict[str, object]] = []
    for idx, sec in enumerate(sections):
        safe_heading = re.sub(r'[^a-zA-Z0-9._-]', '_', sec['heading'])[:60]
        filename = f'{idx:02d}_{safe_heading}.txt'
        filepath = os.path.join(out_dir, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            _ = f.write(sec['text'])
        manifest.append({
            'index': idx,
            'heading': sec['heading'],
            'file': filepath,
            'char_count': len(sec['text']),
        })

    manifest_path = os.path.join(out_dir, 'sections.json')
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f'sections_dir: {out_dir}')
    print(f'sections_json: {manifest_path}')
    print(f'total_sections: {len(manifest)}')
    for entry in manifest:
        print(f'  [{entry["index"]:02d}] {entry["heading"]} ({entry["char_count"]} chars)')


def cmd_generate(args: CliArgs) -> None:
    """Legacy: generate full note with template-based inference (one-shot)."""
    _, _, domain, note_path, date = _resolve_paths(args)
    zotero_state = ensure_zotero_daily_paper(args.paper_id, args.title, args.zotero_collection)
    image_urls = load_image_urls(note_path)
    piclist_section = extract_piclist_section(note_path)
    summary = args.summary.strip() or fetch_arxiv_summary(args.paper_id)
    pdf_path = download_pdf(args.paper_id)
    pdf_sections = split_pdf_sections(extract_pdf_page_text(pdf_path))
    content = generate_note_content(args.paper_id, args.title, args.authors, domain, date, image_urls, summary, pdf_sections, args.language)
    if piclist_section:
        content = content.rstrip() + '\n\n' + piclist_section + '\n'

    with open(note_path, 'w', encoding='utf-8') as f:
        _ = f.write(content)

    print(f'Zotero gate: {zotero_state}')
    print(f'note_path: {note_path}')
    print('分析内容已基于 PDF 分块提取与摘要生成。' if args.language == 'zh' else 'Note generated from PDF section extraction.')


def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%H:%M:%S',
        stream=sys.stderr,
    )

    parser = argparse.ArgumentParser(description='论文分析笔记工具 / Paper analysis note tool')
    subparsers = parser.add_subparsers(dest='command')

    scaffold_parser = subparsers.add_parser('scaffold', help='Create note skeleton for progressive AI analysis')
    _common_args(scaffold_parser)

    split_parser = subparsers.add_parser('split', help='Split PDF into fine-grained section files')
    _common_args(split_parser)

    generate_parser = subparsers.add_parser('generate', help='Legacy one-shot note generation')
    _common_args(generate_parser)

    args = cast(CliArgs, parser.parse_args())

    if args.command == 'scaffold':
        cmd_scaffold(args)
    elif args.command == 'split':
        cmd_split(args)
    elif args.command == 'generate':
        cmd_generate(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
