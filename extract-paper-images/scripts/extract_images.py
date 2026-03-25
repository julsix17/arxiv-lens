#!/usr/bin/env python3

import json
import logging
import os
import re
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from typing import TypedDict, cast

import fitz

logger = logging.getLogger(__name__)

try:
    import requests as requests_lib
except ImportError:
    requests_lib = None

PICLIST_SERVER_URL = os.environ.get('PICLIST_SERVER_URL', 'http://127.0.0.1:36677').rstrip('/')
PICLIST_UPLOAD_URL = f'{PICLIST_SERVER_URL}/upload'
SECTION_START = '%% PICLIST_IMAGE_INDEX_START'
SECTION_END = 'PICLIST_IMAGE_INDEX_END %%'


class Figure(TypedDict):
    filename: str
    local_path: str
    size: int
    ext: str
    source: str


class UploadedFigure(TypedDict):
    filename: str
    url: str
    size: int
    ext: str
    source: str


def ensure_piclist_available() -> None:
    try:
        with urllib.request.urlopen(PICLIST_SERVER_URL, timeout=5) as response:
            status = int(getattr(response, 'status', 200))
            if status != 200:
                raise RuntimeError(f'HTTP {status}')
    except Exception as exc:
        logger.error('PicList server unavailable at %s: %s', PICLIST_SERVER_URL, exc)
        print(f'错误：PicList 未启动或不可访问：{PICLIST_SERVER_URL}', file=sys.stderr)
        print('根据当前工作流要求，图片必须通过 PicList 上传；不允许回退到本地存储。', file=sys.stderr)
        sys.exit(2)


def read_existing_urls(note_path: str) -> dict[str, str]:
    if not os.path.exists(note_path):
        return {}
    content = open(note_path, 'r', encoding='utf-8').read()
    start = content.find(SECTION_START)
    end = content.find(SECTION_END)
    if start == -1 or end == -1 or end < start:
        return {}
    section = content[start:end]
    current_filename = ''
    existing: dict[str, str] = {}
    for raw_line in section.splitlines():
        line = raw_line.strip()
        if line.startswith('- 文件名：'):
            current_filename = line.removeprefix('- 文件名：').strip()
        elif line.startswith('- URL：') and current_filename:
            existing[current_filename] = line.removeprefix('- URL：').strip()
            current_filename = ''
    return existing


def write_note_section(note_path: str, figures: list[UploadedFigure]) -> None:
    grouped: dict[str, list[UploadedFigure]] = {}
    for fig in figures:
        grouped.setdefault(fig['source'], []).append(fig)

    lines = ['', SECTION_START, '## PicList 图片索引', '', f'总计：{len(figures)} 张图片（已通过 PicList 上传）', '']
    for source, items in grouped.items():
        lines.append(f'### 来源: {source}')
        for fig in items:
            lines.extend([
                f'- 文件名：{fig["filename"]}',
                f'- URL：{fig["url"]}',
                f'- 大小：{fig["size"] / 1024:.1f} KB',
                f'- 格式：{fig["ext"]}',
                '',
            ])
    lines.append(SECTION_END)
    section = '\n'.join(lines).rstrip() + '\n'

    existing = ''
    if os.path.exists(note_path):
        existing = open(note_path, 'r', encoding='utf-8').read().rstrip()
        start = existing.find(SECTION_START)
        end = existing.find(SECTION_END)
        if start != -1 and end != -1 and end >= start:
            existing = (existing[:start].rstrip() + '\n').rstrip()

    prefix = existing + '\n\n' if existing else ''
    with open(note_path, 'w', encoding='utf-8') as handle:
        _ = handle.write(prefix + section)


def upload_to_piclist(file_path: str) -> str:
    last_error: Exception | None = None
    for _ in range(3):
        try:
            if requests_lib is not None:
                with open(file_path, 'rb') as file_obj:
                    response = requests_lib.post(PICLIST_UPLOAD_URL, files={'file': file_obj}, timeout=60)
                response.raise_for_status()
                payload = cast(object, response.json())
            else:
                request = urllib.request.Request(
                    PICLIST_UPLOAD_URL,
                    data=json.dumps({'list': [file_path]}).encode('utf-8'),
                    headers={'Content-Type': 'application/json'},
                    method='POST',
                )
                with urllib.request.urlopen(request, timeout=30) as response:
                    payload = cast(object, json.loads(response.read().decode('utf-8')))
            data = cast(dict[str, object], payload if isinstance(payload, dict) else {})
            urls = data.get('result')
            if data.get('success') is True and isinstance(urls, list) and urls and isinstance(urls[0], str):
                return urls[0]
            raise RuntimeError(f'Invalid PicList response: {data}')
        except Exception as exc:
            last_error = exc
            logger.error('上传到 PicList 失败: %s', exc)
    raise RuntimeError(f'PicList upload failed for {file_path}: {last_error}') from last_error


def download_arxiv_source(arxiv_id: str, temp_dir: str) -> bool:
    url = f'https://arxiv.org/e-print/{arxiv_id}'
    print(f'正在下载arXiv源码包: {url}')
    try:
        if requests_lib is not None:
            response = requests_lib.get(url, timeout=60)
            status = response.status_code
            content = response.content if status == 200 else b''
        else:
            with urllib.request.urlopen(url, timeout=60) as response:
                status = int(getattr(response, 'status', 200))
                content = response.read() if status == 200 else b''
        if status != 200 or not content:
            print(f'下载失败: HTTP {status}')
            return False
        tar_path = os.path.join(temp_dir, f'{arxiv_id}.tar.gz')
        with open(tar_path, 'wb') as handle:
            _ = handle.write(content)
        print(f'源码包已下载: {tar_path}')
        with tarfile.open(tar_path, 'r:gz') as archive:
            safe_members = []
            for member in archive.getmembers():
                if member.name.startswith('/') or '..' in member.name or member.issym() or member.islnk():
                    continue
                safe_members.append(member)
            archive.extractall(path=temp_dir, members=safe_members, filter='data')
        print(f'源码已提取到: {temp_dir}')
        return True
    except Exception as exc:
        logger.error('下载源码包失败: %s', exc)
        return False


def collect_source_figures(temp_dir: str) -> list[Figure]:
    figures: list[Figure] = []
    seen: set[str] = set()
    for folder in ('pics', 'figures', 'fig', 'images', 'img'):
        folder_path = os.path.join(temp_dir, folder)
        if not os.path.exists(folder_path):
            continue
        print(f'找到图片目录: {folder_path}')
        for filename in os.listdir(folder_path):
            file_path = os.path.join(folder_path, filename)
            ext = os.path.splitext(filename)[1].lower()
            if not os.path.isfile(file_path) or filename in seen:
                continue
            if ext not in {'.png', '.jpg', '.jpeg', '.pdf', '.eps', '.svg'}:
                continue
            seen.add(filename)
            figures.append(Figure(filename=filename, local_path=file_path, size=os.path.getsize(file_path), ext=ext[1:], source='arxiv-source'))
    if figures:
        return figures
    for filename in os.listdir(temp_dir):
        file_path = os.path.join(temp_dir, filename)
        ext = os.path.splitext(filename)[1].lower()
        if os.path.isfile(file_path) and ext in {'.png', '.jpg', '.jpeg'} and 'logo' not in filename.lower() and 'icon' not in filename.lower():
            figures.append(Figure(filename=filename, local_path=file_path, size=os.path.getsize(file_path), ext=ext[1:], source='arxiv-source'))
    return figures


def extract_pdf_images(pdf_path: str, work_dir: str) -> list[Figure]:
    print('从PDF直接提取图片（备选方案）...')
    figures: list[Figure] = []
    document = fitz.open(pdf_path)
    try:
        for page_num in range(len(document)):
            page = document[page_num]
            for image_index, image_meta in enumerate(page.get_images(full=True)):
                xref = int(image_meta[0])
                try:
                    image = cast(dict[str, object], document.extract_image(xref))
                except Exception as exc:
                    logger.warning('跳过无法提取的图片 (page %d, xref %d): %s', page_num + 1, xref, exc)
                    continue
                image_bytes = image.get('image')
                image_ext = image.get('ext')
                if not isinstance(image_bytes, (bytes, bytearray)) or not isinstance(image_ext, str):
                    continue
                filename = f'page{page_num + 1}_fig{image_index + 1}.{image_ext}'
                output_path = os.path.join(work_dir, filename)
                with open(output_path, 'wb') as handle:
                    _ = handle.write(bytes(image_bytes))
                figures.append(Figure(filename=filename, local_path=output_path, size=len(image_bytes), ext=image_ext, source='pdf-extraction'))
    finally:
        document.close()
    return figures


def rasterize_pdf_figure(pdf_path: str, work_dir: str) -> list[Figure]:
    print(f'从PDF图片文件提取: {os.path.basename(pdf_path)}')
    figures: list[Figure] = []
    document = fitz.open(pdf_path)
    base = os.path.splitext(os.path.basename(pdf_path))[0]
    try:
        for page_index in range(len(document)):
            pixmap = document[page_index].get_pixmap(dpi=150)
            filename = f'{base}_page{page_index + 1}.png'
            output_path = os.path.join(work_dir, filename)
            pixmap.save(output_path)
            figures.append(Figure(filename=filename, local_path=output_path, size=os.path.getsize(output_path), ext='png', source='pdf-figure'))
    finally:
        document.close()
    return figures


def collect_figures(paper_input: str, note_path: str) -> list[UploadedFigure]:
    figures: list[Figure] = []
    pdf_path: str | None = paper_input if os.path.isfile(paper_input) else None
    arxiv_id = paper_input
    if pdf_path is not None:
        match = re.search(r'(\d{4}\.\d+)', os.path.basename(pdf_path))
        arxiv_id = match.group(1) if match else ''
        if arxiv_id:
            print(f'检测到arXiv ID: {arxiv_id}')

    with tempfile.TemporaryDirectory() as temp_dir:
        extracted_dir = os.path.join(temp_dir, 'extracted')
        os.makedirs(extracted_dir, exist_ok=True)
        if arxiv_id and download_arxiv_source(arxiv_id, temp_dir):
            source_figures = collect_source_figures(temp_dir)
            if source_figures:
                print(f'\n从arXiv源码找到 {len(source_figures)} 个图片文件')
                for fig in source_figures:
                    print(f'  - {fig["filename"]}')
                figures.extend(source_figures)
            for root, _, files in os.walk(temp_dir):
                for file in files:
                    if file.endswith('.pdf') and 'logo' not in file.lower() and file != f'{arxiv_id}.tar.gz':
                        figures.extend(rasterize_pdf_figure(os.path.join(root, file), extracted_dir))
        if len(figures) < 3 and pdf_path is not None:
            print('\n找到的图片数量较少，从PDF直接提取...')
            figures.extend(extract_pdf_images(pdf_path, extracted_dir))

        collected: list[Figure] = []
        seen_names: set[str] = set()
        for fig in figures:
            if fig['filename'] in seen_names:
                continue
            seen_names.add(fig['filename'])
            copied_path = fig['local_path']
            if not copied_path.startswith(temp_dir):
                copied_path = os.path.join(extracted_dir, fig['filename'])
                with open(fig['local_path'], 'rb') as source_handle, open(copied_path, 'wb') as target_handle:
                    _ = target_handle.write(source_handle.read())
            collected.append(Figure(filename=fig['filename'], local_path=copied_path, size=fig['size'], ext=fig['ext'], source=fig['source']))

        existing_urls = read_existing_urls(note_path)
        final: list[UploadedFigure] = []
        for fig in collected:
            filename = fig['filename']
            local_path = fig['local_path']
            remote_url = existing_urls.get(filename) or upload_to_piclist(local_path)
            final.append(UploadedFigure(filename=filename, url=remote_url, size=fig['size'], ext=fig['ext'], source=fig['source']))
        return final


def main() -> int:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S', stream=sys.stderr)
    if len(sys.argv) < 3:
        print('Usage: python extract_images.py <paper_id_or_pdf> <note_path>', file=sys.stderr)
        return 1
    paper_input = sys.argv[1]
    note_path = sys.argv[2]
    ensure_piclist_available()
    os.makedirs(os.path.dirname(note_path) or '.', exist_ok=True)
    uploaded = collect_figures(paper_input, note_path)
    write_note_section(note_path, uploaded)
    print(f'\n成功提取 {len(uploaded)} 张图片')
    print('图片已通过 PicList 上传，并写入主 note 末尾')
    print(f'更新笔记：{note_path}')
    print('\nImage URLs:')
    for fig in uploaded:
        print(fig['url'])
    return 0


if __name__ == '__main__':
    sys.exit(main())
