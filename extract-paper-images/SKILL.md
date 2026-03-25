---
name: extract-paper-images
description: 从论文中提取图片，优先从arXiv源码包获取真正的论文图
allowed-tools: Read, Write, Bash
---
You are the Paper Image Extractor for OrbitOS.

# 目标
从论文中提取所有图片，**必须通过 PicList 上传**后把远程图片 URL 记录到论文主 note 的末尾，以便在笔记中引用。

**关键改进**：优先从arXiv源码包提取真正的论文图片（架构图、实验结果图等），而非PDF中的logo等非核心图片。

# 工作流程

## 步骤1：识别论文来源

1. **识别论文来源**
   - 支持格式：arXiv ID（如2510.24701）、完整ID（arXiv:2510.24701）、本地PDF路径

2. **下载PDF（如果需要）**
   - 如果是arXiv ID，使用curl下载PDF到临时目录

## 步骤2：提取图片（三级优先级）

### 优先级1：从arXiv源码包提取（最高优先级）

脚本会自动尝试以下步骤：

1. **下载arXiv源码包**
   - URL：`https://arxiv.org/e-print/[PAPER_ID]`
   - 解压到临时目录

2. **查找源码中的图片目录**
   - 检查目录：`pics/`、`figures/`、`fig/`、`images/`、`img/`
   - 如果找到，将这些图片文件加入上传队列

3. **提取源码中的PDF图片**
   - 查找源码包中的PDF文件（如`dr_pipelinev2.pdf`）
   - 将PDF页面转换为PNG图片

4. **上传到 PicList 并写回主 note**
   - 在返回结果前，必须把所有提取出的图片上传到 PicList server：`http://127.0.0.1:36677/upload`
   - 按来源分组（arxiv-source、pdf-figure、pdf-extraction）
   - 将远程 URL 追加到论文主 note 末尾，不记录本地路径

### 优先级2：从PDF直接提取（备选方案）

如果源码包不可用或未找到足够图片，回退到从PDF中提取：

```bash
python "scripts/extract_images.py" \
  "[PAPER_ID or PDF_PATH]" \
  "$OBSIDIAN_VAULT_PATH/20_Research/Papers/[DOMAIN]/[PAPER_TITLE].md"
```

**参数说明**：
- 第1个参数：论文ID（arXiv ID）或本地PDF路径
- 第2个参数：论文主 note 路径；脚本会把 PicList URL 记录到该文件末尾

## 步骤3：返回图片 URL

返回 PicList 上传后的远程图片 URL 列表，格式化输出便于在笔记中引用。

# 提取策略详解

### 为什么优先从源码包提取？

**PDF直接提取的问题**：
1. **Logo等非核心图片**：PDF中的logo、图标、装饰元素被当成图片
2. **矢量图无法识别**：论文中的架构图可能是LaTeX矢量图，不是独立图片对象
3. **多层PDF结构**：实验结果图可能是复杂渲染对象

**arXiv源码包的优势**：
1. **真正的论文图**：`pics/`目录包含作者准备的原始图片
2. **高质量**：源码中的图通常是高分辨率矢量图
3. **清晰命名**：文件名描述图片内容（如`dr_pipelinev2.pdf`）

# 输出格式

## 主 note 末尾记录格式

```markdown
<!-- PICLIST_IMAGE_INDEX_START -->
## PicList 图片索引

总计：X 张图片

## 来源: arxiv-source
- 文件名：final_results_combined.pdf
- URL：https://your-cdn.example/final_results_combined_page1.png
- 大小：1500.5 KB
- 格式：png

## 来源: pdf-figure
- 文件名：dr_pipelinev2_page1.png
- URL：https://your-cdn.example/dr_pipelinev2_page1.png
- 大小：45.2 KB
- 格式：png

## 来源: pdf-extraction
- 文件名：page1_fig15.png
- URL：https://your-cdn.example/page1_fig15.png
- 大小：65.3 KB
- 格式：png
<!-- PICLIST_IMAGE_INDEX_END -->
```

## 返回的图片 URL

```
Image URLs:
https://your-cdn.example/final_results_combined_page1.png (arxiv-source)
https://your-cdn.example/dr_pipelinev2_page1.png (pdf-figure)
https://your-cdn.example/rl_framework_page1.png (pdf-figure)
https://your-cdn.example/question_synthesis_pipeline_page1.png (pdf-figure)
```

# 使用说明

## 调用方式

```bash
/extract-paper-images 2510.24701
```

## 返回内容

- 论文标题
- 图片 URL 记录：`20_Research/Papers/领域/论文标题.md` 文件末尾
- 核心图片：PicList 返回的远程 URL（前3-5张）
- 图片来源标识（arxiv-source、pdf-figure、pdf-extraction）

# 重要规则

- **必须依赖 PicList**：运行前必须检测 `http://127.0.0.1:36677` 可用，否则立即报错退出
- **禁止本地回退**：PicList 不可用时，不允许改为本地图片存储流程
- **重复运行要复用 URL**：如果主 note 末尾已经存在相同文件名对应的 PicList URL，必须直接复用，不能重复上传同一张图
- **图片元数据写回主 note**：记录所有图片远程 URL 和来源，不创建 `images/` 子文件夹
- **图片质量**：确保清晰度足够高
- **优先源码图片**：arXiv源码包中的图片优先于PDF提取
- **来源标识**：在索引中标注图片来源，便于区分

# 问题排查

**如果提取的都是logo/图标**：
1. 检查是否有arXiv源码包可用
2. 查看`pics/`或`figures/`目录
3. 查看索引文件中的"来源"字段

**如果arXiv源码包下载失败**：
1. 检查网络连接
2. 检查arXiv ID格式（YYYYMM.NNNNN）
3. 脚本会自动回退到PDF提取模式

# 依赖项

- Python 3.x
- PyMuPDF（fitz）
- requests库（用于下载arXiv源码包）
- 网络连接（访问arXiv）

# 版本历史

## v2.0 (2025-02-28)
- **新增**：优先从arXiv源码包提取图片
- **新增**：三级优先级提取策略（源码包 > PDF图 > PDF提取）
- **新增**：图片来源标识（arxiv-source、pdf-figure、pdf-extraction）
- **新增**：从PDF图片文件提取为PNG的功能

## v1.0
- 初始版本：仅从PDF直接提取图片
