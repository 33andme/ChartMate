"""
rag.py - RAG 知识库模块
使用 LanceDB 本地向量库（兼容 Python 3.8，无 sqlite3 版本要求）
Embedding 使用 sentence-transformers 本地模型（无需 API Key）
"""
import os
import io
from typing import Optional

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

LANCE_PATH = "./lance_db"
TABLE_NAME = "astro_knowledge"
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50

_db = None
_table = None
_embed_model = None


def _get_embed_model():
    global _embed_model
    if _embed_model is not None:
        return _embed_model
    from sentence_transformers import SentenceTransformer
    _embed_model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
    return _embed_model


def _embed(texts):
    model = _get_embed_model()
    return model.encode(texts, normalize_embeddings=True).tolist()


def _get_table():
    global _db, _table
    if _table is not None:
        return _table

    import lancedb
    import pyarrow as pa

    _db = lancedb.connect(LANCE_PATH)
    schema = pa.schema([
        pa.field("id", pa.string()),
        pa.field("doc_id", pa.string()),
        pa.field("filename", pa.string()),
        pa.field("chunk_index", pa.int32()),
        pa.field("text", pa.string()),
        pa.field("vector", pa.list_(pa.float32(), 384)),
    ])

    if TABLE_NAME in _db.table_names():
        _table = _db.open_table(TABLE_NAME)
    else:
        _table = _db.create_table(TABLE_NAME, schema=schema)

    return _table


def _chunk_text(text: str):
    chunks = []
    start = 0
    while start < len(text):
        end = start + CHUNK_SIZE
        chunks.append(text[start:end])
        start += CHUNK_SIZE - CHUNK_OVERLAP
    return [c for c in chunks if c.strip()]


def extract_text(file_bytes: bytes, filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower()

    if ext == "txt":
        return file_bytes.decode("utf-8", errors="ignore")

    if ext == "pdf":
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(file_bytes))
        return "\n".join(page.extract_text() or "" for page in reader.pages)

    if ext in ("docx", "doc"):
        from docx import Document
        doc = Document(io.BytesIO(file_bytes))
        return "\n".join(p.text for p in doc.paragraphs)

    raise ValueError(f"不支持的文件类型: {ext}")


def add_document(doc_id: str, text: str, metadata: dict) -> int:
    table = _get_table()
    chunks = _chunk_text(text)
    if not chunks:
        return 0

    delete_document(doc_id)

    vectors = _embed(chunks)
    filename = metadata.get("filename", "")
    rows = [
        {
            "id": f"{doc_id}_chunk_{i}",
            "doc_id": doc_id,
            "filename": filename,
            "chunk_index": i,
            "text": chunk,
            "vector": vectors[i],
        }
        for i, chunk in enumerate(chunks)
    ]
    table.add(rows)
    return len(chunks)


def delete_document(doc_id: str):
    table = _get_table()
    try:
        table.delete(f"doc_id = '{doc_id}'")
    except Exception:
        pass


def get_chunks(doc_id: str):
    """返回某文档所有切块，按 chunk_index 排序"""
    table = _get_table()
    try:
        results = (
            table.search()
            .where(f"doc_id = '{doc_id}'")
            .select(["chunk_index", "text"])
            .to_list()
        )
        return sorted(results, key=lambda x: x["chunk_index"])
    except Exception:
        return []


def search(query: str, n_results: int = 3):
    table = _get_table()
    try:
        if table.count_rows() == 0:
            return []
    except Exception:
        return []

    query_vec = _embed([query])[0]
    results = (
        table.search(query_vec)
        .limit(n_results)
        .select(["text"])
        .to_list()
    )
    return [r["text"] for r in results]
