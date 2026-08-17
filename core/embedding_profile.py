"""向量维度 profile — 模型适配（8B=4096 / 2B=2048）。

embedding_profile 由 config_loader 在 load_config() 时按 config.yaml 的
`embedding_profile` 档位解析，并在此设置全局维度；ORM 建表（create_all）与
db.py 增量迁移用该维度，保证「表维度永远跟模型走」。

EmbedVector：维度懒读取的 pgvector 类型。`Vector(4096)` 在类定义时就把维度
钉死；子类化后在 get_col_spec()（DDL 编译时刻，即 create_all 运行时）才取全局
维度 —— 这样 config 已加载、维度已设置，建出的表就是当前模型对应的维度。
"""

from pgvector.sqlalchemy import Vector

_EMBED_DIM: int = 4096  # 默认 8B；load_config() 按 embedding_profile 设置


def set_embed_dim(dim: int) -> None:
    """设置当前向量维度（由 config_loader 在解析 embedding_profile 时调用）。"""
    global _EMBED_DIM
    _EMBED_DIM = int(dim)


def get_embed_dim() -> int:
    """当前向量维度（EmbedVector 建表时 / db.py 迁移时读取）。"""
    return _EMBED_DIM


class EmbedVector(Vector):
    """维度跟随当前 embedding_profile 的向量列类型。

    用法：`mapped_column(EmbedVector(), ...)` —— 建表时维度 = get_embed_dim()。
    人脸向量用固定 Vector(512)（ArcFace，独立于 embedding profile）。
    """

    cache_ok = True

    def get_col_spec(self, **kw):
        return "VECTOR(%d)" % get_embed_dim()
