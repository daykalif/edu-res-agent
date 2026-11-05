from pydoc import doc
from typing import final
from chromadb.api.models.Collection import Collection
from chromadb.utils import embedding_functions
import chromadb
from app.config import BASE_DIR

# 知识库文件来源地址
KB_DIR = BASE_DIR / "data" / "kb"
# 向量库的存储地址
CHROMA_DIR = BASE_DIR / "data" / "chroma"
# 集合，用于存储从文档中加载出来的向量，只加载一次。
_collection = None

# 给 chromadb 使用，把文本转为向量，用来相似度检索。智源 BGE 系列，中文轻量嵌入模型，RAG 中文场景很常用
_embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name="BAAI/bge-small-zh-v1.5"
)


def get_collcetion() -> Collection:
    """向量库的初始化"""

    global _collection
    if _collection is not None:
        return _collection

    # 创建KB_DIR文件夹（以防万一文件夹不存在报错）
    KB_DIR.mkdir(parents=True, exist_ok=True)

    # 如果CHROMA_DIR文件夹不存在，则创建；如果存在，则跳过。
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))

    # 将本地文件夹中的md文件加载到向量库
    col = client.get_or_create_collection(
        name="lab_kb", embedding_function=_embedding_fn
    )
    # 加载的过程：1. 遍历KB_DIR文件夹下的所有md文件；2. 读取文件内容；3. 添加到向量库。
    if col.count() == 0:
        ids = []
        docs = []
        metas = []
        for path in sorted(KB_DIR.glob("*.md")):  # 排序
            text = path.read_text(encoding="UTF-8").strip()  # 读取文件内容
            if not text:
                continue
            docs.append(text)  # 文件内容作为文档
            ids.append(path.stem)  # 文件名作为id（同一个文件夹中，文件名唯一）
            metas.append({"source": path.name})  # 来源，即文件实际路径
        if docs:
            col.add(ids=ids, documents=docs, metadatas=metas)
    _collection = col
    return col


def search(query: str):
    """根据关键字去检索向量库"""

    # 获取向量库
    col = get_collcetion()
    if col.count() == 0:
        return ""

    # 从向量库中检索
    limit = min(5, col.count())  # 限制返回的条数，避免过少；最多5条
    res = col.query(query_texts=[query], n_results=limit)
    docs = (res.get("documents") or [[]])[0]
    metas = (res.get("metadatas") or [[]])[0]
    distances = (res.get("distances") or [[]])[0]  # 距离，即评分

    """
    以下是检索出来的资料：
    [预约规则.md]

    # 实验室预约规则...

    
    [安全规范.md]

    # 实验室安全规范...
    """
    score_parts = []

    # zip：同时遍历多个序列，每次返回各组对应的元素
    for doc, metas, dist in zip(docs, metas, distances):
        # 分值范围0~1，越接近1代表相关性越高
        score = 1 / (1 + dist)
        # 低于0.5分的直接过滤掉
        if score < 0.5:
            continue
        # 取元数据里的来源字段，取不到就为空字符串
        name = metas.get("source") or ""
        # 组装结果：相似度分数 + 文档内容（带上来源标记）
        score_parts.append({"score": score, "content": f"[{name}]\n{doc}"})

    print(f"\n\n\n\n以下是检索出来的资料：{score_parts}\n\n\n\n")

    # 按相似度分数从高到低排序
    score_parts.sort(key=lambda x: x["score"], reverse=True)
    # 取前2条，只保留content文本
    final_parts = [item["content"] for item in score_parts[:2]]
    # 两条内容用两个换行隔开，拼接成字符串返回
    return "\n\n".join(final_parts)
