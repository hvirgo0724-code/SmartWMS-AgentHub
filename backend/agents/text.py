"""轻量文本处理：中文分词、BM25、哈希向量（无第三方依赖，可离线运行）"""
import re
import math
import hashlib
from collections import Counter

_CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")
_WORD = re.compile(r"[a-zA-Z0-9_\-]+")
_STOP_CHARS = set("的了吗呢啊吧呀哦嗯我你您他她它这那个有在和与及或是就都也还很最着把被给对从向为")

VECTOR_DIM = 512


def tokenize(text: str) -> list:
    """中文按字 + 二元词切分，英文/数字按词切分；保留意图词（如“怎么/多少”）"""
    if not text:
        return []
    text = str(text).lower()
    tokens = _WORD.findall(text)
    for run in _CJK_RUN.findall(text):
        for ch in run:
            if ch not in _STOP_CHARS:
                tokens.append(ch)
        for i in range(len(run) - 1):
            tokens.append(run[i:i + 2])
        for i in range(len(run) - 3):
            if run[i] not in _STOP_CHARS and run[i + 1] not in _STOP_CHARS:
                tokens.append(run[i:i + 3])
    return tokens


def term_freq(text: str) -> Counter:
    return Counter(tokenize(text))


def _bucket(token: str) -> int:
    h = hashlib.md5(token.encode("utf-8")).hexdigest()
    return int(h[:8], 16) % VECTOR_DIM


def embed(text: str) -> dict:
    """哈希词袋向量（稀疏存储：{维度索引: 权重}），L2 归一化，用于语义召回兜底"""
    tf = term_freq(text)
    if not tf:
        return {}
    total = sum(tf.values())
    vec = {}
    for token, cnt in tf.items():
        idx = _bucket(token)
        weight = (1.0 + math.log(cnt)) / total
        vec[idx] = vec.get(idx, 0.0) + weight
    norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
    return {k: round(v / norm, 5) for k, v in vec.items()}


def cosine(a: dict, b: dict) -> float:
    if not a or not b:
        return 0.0
    if len(a) > len(b):
        a, b = b, a
    return sum(w * b.get(k, 0.0) for k, w in a.items())


def bm25(query_tokens: list, docs_tokens: list, k1: float = 1.5, b: float = 0.75) -> list:
    """标准 BM25，返回与 docs_tokens 等长的分数列表"""
    n = len(docs_tokens)
    if not n or not query_tokens:
        return [0.0] * n
    avgdl = sum(len(d) for d in docs_tokens) / n or 1.0
    df = Counter()
    for doc in docs_tokens:
        for term in set(doc):
            df[term] += 1
    idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}
    scores = []
    for doc in docs_tokens:
        dl = len(doc) or 1
        tf = Counter(doc)
        score = 0.0
        for term in query_tokens:
            if term not in tf:
                continue
            freq = tf[term]
            score += idf.get(term, 0.0) * (freq * (k1 + 1)) / (freq + k1 * (1 - b + b * dl / avgdl))
        scores.append(score)
    return scores


def normalize_scores(scores: list) -> list:
    if not scores:
        return []
    lo, hi = min(scores), max(scores)
    if hi - lo < 1e-9:
        return [0.0 for _ in scores]
    return [(s - lo) / (hi - lo) for s in scores]


def excerpt(content: str, query: str, size: int = 170) -> str:
    """截取与问题最相关的片段"""
    content = re.sub(r"\s+", " ", content or "").strip()
    if len(content) <= size:
        return content
    tokens = [t for t in tokenize(query) if len(t) >= 2]
    pos = -1
    for t in sorted(tokens, key=len, reverse=True):
        p = content.find(t)
        if p >= 0:
            pos = p
            break
    if pos < 0:
        return content[:size] + "…"
    start = max(0, pos - size // 3)
    end = min(len(content), start + size)
    return ("…" if start else "") + content[start:end] + ("…" if end < len(content) else "")
