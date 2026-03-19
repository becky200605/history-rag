# 知识库 Citation / 定位 冒烟清单

## 目标

验证以下链路：

1. PDF 文献能被检索到。
2. 回答里的 citation 默认指向原始 PDF，而不是 `.structured.json`。
3. citation 点击后打开内部定位查看页。
4. 定位查看页能显示：
   - PDF 页截图
   - 页码映射
   - 段落原文
   - bbox 高亮框（如果文档带 bbox）
5. 对没有 bbox 的旧本地 OCR 文档，仍然能打开定位查看页，但只保证页级定位。

## 预备文档

优先用这两份现有文档：

- `knowledge/docs/.ingestion/民国财政史 (杨荫溥).pdf.structured.json`
- `knowledge/docs/.ingestion/中华民国史档案资料汇编9 第3辑 财政1 .pdf.structured.json`

对应原始 PDF：

- `knowledge/docs/民国财政史 (杨荫溥).pdf`
- `knowledge/docs/中华民国史档案资料汇编9 第3辑 财政1 .pdf`

## 冒烟用例

### 用例 1：百度解析文档的 bbox viewer

提问建议：

`《民国财政史》中“本期内若干年度北洋军阀政府财政盈亏情况”这一表题在哪？`

预期：

1. 回答命中《民国财政史》。
2. citation 形如：
   `民国财政史 (杨荫溥) 原书第X页第Y段（PDF第Z页）`
3. 点击 citation 后，不是直接打开 `.structured.json`。
4. 新页面路径应类似：
   `/workspace/knowledge/view?...`
5. 页面右侧能看到原文片段。
6. 页面左侧 PDF 截图上能看到绿色高亮框。

### 用例 2：旧本地 OCR 文档的页级定位兜底

提问建议：

`请找出《中华民国史档案资料汇编9 第3辑 财政1》中原书第210页附近的相关财政记载。`

预期：

1. citation 指向原始 PDF。
2. citation label 里包含：
   - 原书页码
   - PDF 页码
   - 段号
3. 点击 citation 后进入定位查看页。
4. 能看到：
   - PDF 页截图
   - 原文片段
5. 如果该旧文档还没重跑新本地 OCR，页面会提示“当前文档还没有 paragraph bbox，只能做到页级定位”。

### 用例 3：citation 链接编码正确

直接检查回答里的 citation 链接。

预期：

1. 链接目标是 `.pdf`
2. 不应出现 `%25E4%25B8...` 这种二次编码
3. URL 应包含参数：
   - `page_no`
   - `pdf_page_no`
   - `paragraph_no`
4. URL 末尾应保留 `#page=...`

### 用例 4：viewer 页面回退能力

直接访问类似链接：

`/workspace/knowledge/view?filename=民国财政史%20(杨荫溥).pdf&pdf_page_no=1&paragraph_no=1`

预期：

1. 页面可打开
2. 能拉到 paragraph 定位信息
3. 对百度旧文档，`position` 会被自动转成 bbox

### 用例 5：重新上传后的本地 OCR bbox

重新上传一份横排 PDF，走本地 PaddleOCR。

预期：

1. 生成新的 `.structured.json`
2. 新结构里的 paragraph 带 `bbox`
3. citation viewer 能显示高亮框

## 额外检查

打开这两个接口确认：

1. 段落定位接口

`/api/knowledge/docs/<pdf文件名>/paragraph-location?page_no=...&pdf_page_no=...&paragraph_no=...`

应返回：

- `bbox`
- `page_meta`
- `text`

2. 页面截图接口

`/api/knowledge/docs/<pdf文件名>/page-image?pdf_page_no=...`

应返回 PNG。

## 通过标准

满足下面 4 条即可判定本轮功能通过：

1. citation 不再跳 `.structured.json`
2. citation 点击后进入内部定位查看页
3. viewer 能显示原文片段和页码映射
4. 至少一份带 bbox 的文档能在截图上看到高亮框
