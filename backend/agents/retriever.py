"""RAG 知识库：文档切片、索引、混合检索（BM25 + 哈希语义向量）"""
import json
import time
import re

from config import KB_CHUNK_SIZE, KB_CHUNK_OVERLAP, KB_TOP_K, KB_MIN_SCORE
from database import query, query_one, execute
from agents.text import (tokenize, embed, cosine, bm25, normalize_scores, excerpt)

_INDEX = {"ts": 0.0, "data": None}
_INDEX_TTL = 20  # 秒级缓存，知识库变更后主动失效


def invalidate_cache():
    _INDEX["ts"] = 0.0
    _INDEX["data"] = None


# ---------- 切片 ----------
def chunk_text(content: str, size: int = None, overlap: int = None) -> list:
    """按段落 + 句子边界切片，保留语义完整性"""
    size = size or KB_CHUNK_SIZE
    overlap = overlap or KB_CHUNK_OVERLAP
    content = (content or "").replace("\r\n", "\n").strip()
    if not content:
        return []

    pieces = []
    for para in re.split(r"\n{2,}", content):
        para = para.strip()
        if not para:
            continue
        if len(para) <= size:
            pieces.append(para)
            continue
        # 长段落按句子切分
        sentences = re.split(r"(?<=[。！？；!?;\n])", para)
        buf = ""
        for sent in sentences:
            if not sent.strip():
                continue
            if len(buf) + len(sent) > size and buf:
                pieces.append(buf.strip())
                buf = buf[-overlap:] if overlap and len(buf) > overlap else ""
            buf += sent
        if buf.strip():
            pieces.append(buf.strip())

    # 合并过短片段
    merged = []
    for p in pieces:
        if merged and len(merged[-1]) < size * 0.5 and len(merged[-1]) + len(p) <= size:
            merged[-1] = merged[-1] + "\n" + p
        else:
            merged.append(p)
    return merged


def ingest_document(doc_id: int, title: str, content: str, conn=None) -> int:
    """重建单篇文档的切片与向量索引，返回切片数"""
    chunks = chunk_text(content)
    run = (lambda sql, params=None: execute(sql, params, conn)) if conn else execute
    run("DELETE FROM kb_chunk WHERE doc_id=%s", (doc_id,))
    for i, chunk in enumerate(chunks):
        vec = embed(f"{title} {chunk}")
        if conn:
            execute("INSERT INTO kb_chunk (doc_id, chunk_index, content, token_count, embedding) VALUES (%s,%s,%s,%s,%s)",
                    (doc_id, i, chunk, len(tokenize(chunk)), json.dumps(vec, ensure_ascii=False)), conn)
        else:
            execute("INSERT INTO kb_chunk (doc_id, chunk_index, content, token_count, embedding) VALUES (%s,%s,%s,%s,%s)",
                    (doc_id, i, chunk, len(tokenize(chunk)), json.dumps(vec, ensure_ascii=False)))
    execute("UPDATE kb_document SET chunk_count=%s, update_time=NOW() WHERE id=%s", (len(chunks), doc_id), conn)
    invalidate_cache()
    return len(chunks)


def rebuild_all() -> dict:
    docs = query("SELECT id, title, content FROM kb_document WHERE status='published'")
    total = 0
    for doc in docs:
        total += ingest_document(doc["id"], doc["title"], doc["content"], None)
    return {"documents": len(docs), "chunks": total}


# ---------- 索引 ----------
def _load_index(force: bool = False):
    now = time.time()
    if not force and _INDEX["data"] is not None and now - _INDEX["ts"] < _INDEX_TTL:
        return _INDEX["data"]
    docs = query("""SELECT id, doc_no, title, category, content, version, update_time
                    FROM kb_document WHERE status='published' ORDER BY id""")
    chunks = query("""SELECT c.id, c.doc_id, c.chunk_index, c.content, c.embedding
                      FROM kb_chunk c JOIN kb_document d ON c.doc_id=d.id
                      WHERE d.status='published' ORDER BY c.doc_id, c.chunk_index""")
    doc_map = {d["id"]: d for d in docs}
    items = []
    for c in chunks:
        doc = doc_map.get(c["doc_id"])
        if not doc:
            continue
        try:
            vec = json.loads(c["embedding"] or "{}")
        except ValueError:
            vec = {}
        items.append({
            "chunk_id": c["id"], "chunk_index": c["chunk_index"], "doc": doc,
            "content": c["content"], "vector": vec,
            "tokens": tokenize(f"{doc['title']} {doc['title']} {c['content']}"),
        })
    data = {"items": items, "docs": docs}
    _INDEX.update(ts=now, data=data)
    return data


def search_knowledge(q: str, top_k: int = None, category: str = None,
                     categories: list = None, min_score: float = None) -> list:
    """混合检索：BM25 稀疏召回 + 哈希向量语义召回，融合排序并按文档去重"""
    top_k = top_k or KB_TOP_K
    min_score = KB_MIN_SCORE if min_score is None else min_score
    q = (q or "").strip()
    if len(q) < 2:
        return []
    cats = categories or ([category] if category else None)
    index = _load_index()
    items = index["items"]
    if cats:
        items = [it for it in items if it["doc"]["category"] in cats]
    if not items:
        return []

    q_tokens = tokenize(q)
    q_vec = embed(q)
    bm = bm25(q_tokens, [it["tokens"] for it in items])
    cos = [cosine(q_vec, it["vector"]) for it in items]
    nb = normalize_scores(bm)
    nc = normalize_scores(cos)

    scored = []
    q_terms = {t for t in q_tokens if len(t) >= 2}
    for i, it in enumerate(items):
        score = 0.58 * nb[i] + 0.42 * nc[i]
        title = it["doc"]["title"]
        if any(t in title for t in q_terms):
            score += 0.10
        if cats and it["doc"]["category"] in cats:
            score += 0.05
        scored.append((score, it))

    scored.sort(key=lambda x: x[0], reverse=True)
    results, used_docs = [], {}
    for score, it in scored:
        if score < min_score:
            break
        did = it["doc"]["id"]
        if used_docs.get(did, 0) >= 2:        # 每篇文档最多贡献 2 个切片
            continue
        used_docs[did] = used_docs.get(did, 0) + 1
        results.append({
            "doc_id": did,
            "doc_no": it["doc"]["doc_no"],
            "title": it["doc"]["title"],
            "category": it["doc"]["category"],
            "chunk_index": it["chunk_index"],
            "content": it["content"],
            "excerpt": excerpt(it["content"], q),
            "score": round(score, 4),
        })
        if len(results) >= top_k:
            break
    return results


def kb_stats() -> dict:
    doc = query_one("""SELECT COUNT(*) total, SUM(status='published') published,
                              SUM(status='draft') draft, SUM(chunk_count) chunks
                       FROM kb_document""") or {}
    return {"documents": int(doc.get("total") or 0), "published": int(doc.get("published") or 0),
            "draft": int(doc.get("draft") or 0), "chunks": int(doc.get("chunks") or 0)}
