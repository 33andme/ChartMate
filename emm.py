import os
# 强制使用国内镜像！解决超时问题
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

from sentence_transformers import SentenceTransformer

# 直接下载，不会再超时！
model = SentenceTransformer(
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    cache_folder="./models"  # 模型会下载到你项目里的 models 文件夹
)

# 测试
embedding = model.encode("测试星盘系统")
print("✅ 模型下载 + 加载成功！向量维度：", embedding.shape)