# RAG 知识库实现

## 涉及文件
- `rag.py` — 向量库核心逻辑
- `models.py` — `KnowledgeDoc` 表（第 237-248 行）
- `main.py` — 后台管理页面（`KnowledgeAdmin`，第 274-438 行）
- `agent.py` — RAG 检索注入（第 189-195 行）

---

## 技术栈

| 组件 | 实现 |
|------|------|
| Embedding 模型 | `paraphrase-multilingual-MiniLM-L12-v2`（HuggingFace 本地运行） |
| 向量数据库 | LanceDB（本地文件，存储在 `./lance_db/`） |
| 文档切块 | LangChain `RecursiveCharacterTextSplitter` |
| 集成框架 | LangChain + `langchain_community.vectorstores.LanceDB` |

---

## 核心流程

### 上传文档
```
管理员上传文件（PDF/DOCX/TXT）
  ↓
extract_text()：解析文件内容为纯文本
  ↓
_chunk_text()：按语义切块（500字/块，50字重叠）
  ↓
add_document()：先删旧数据（幂等），再批量写入向量库
  ↓
KnowledgeDoc 表记录文件信息和切块数量
```

### 检索
```
用户消息 → search(query, n_results=3)
  ↓
HuggingFace Embedding 将 query 转为向量
  ↓
LanceDB 余弦相似度检索，返回最相关的 3 条文本块
  ↓
注入 System Prompt：
  "【知识库参考】\n 内容1 \n---\n 内容2 ..."
```

---

## 文档解析（`rag.py` 第 86 行）

`extract_text(file_bytes, filename)`：

| 格式 | 解析方式 |
|------|---------|
| `.txt` | 直接 UTF-8 解码 |
| `.pdf` | `pypdf.PdfReader`，逐页提取文字 |
| `.docx/.doc` | `python-docx`，逐段落提取 |

---

## 切块策略（`rag.py` 第 76 行）

```python
RecursiveCharacterTextSplitter(
    chunk_size=500,      # 每块最大 500 字
    chunk_overlap=50,    # 相邻块重叠 50 字，保持上下文连续性
    separators=["\n\n", "\n", "。", "！", "？", ".", "!", "?", " ", ""]
)
```

优先按段落（`\n\n`）、换行（`\n`）、句号切割，尽量保证每块语义完整。

---

## 向量库初始化（`rag.py` 第 34 行）

LanceDB 不支持空表建库，首次初始化时写入一条占位文档，建表后立即删除：

```python
placeholder = Document(page_content="__init__", ...)
LanceDB.from_documents([placeholder], ...)
db.open_table(TABLE_NAME).delete("metadata.doc_id = '__init__'")
```

全局单例 `_vectorstore` 和 `_embeddings` 避免每次请求重新加载模型（HuggingFace 模型首次加载需要数秒）。

---

## 后台管理（`main.py` 第 274 行）

通过 sqladmin `BaseView` 实现自定义 HTML 管理页：

| 路由 | 功能 |
|------|------|
| `GET /admin/knowledge` | 文档列表页（带上传表单） |
| `POST /admin/knowledge/upload` | 接收文件，解析并入库 |
| `GET /admin/knowledge/chunks/{doc_id}` | 预览某文档所有切块内容 |
| `POST /admin/knowledge/delete` | 从向量库 + 数据库同时删除文档 |

---

## Embedding 镜像配置

```python
# rag.py 第 10 行
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
```

国内环境下载 HuggingFace 模型时走镜像站，避免超时。
