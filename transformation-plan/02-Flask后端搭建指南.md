# 02 - Flask 后端搭建指南

> 本文档面向 AI 开发者，详细描述"数分精灵"项目 Flask 后端的完整搭建过程，涵盖环境准备、配置管理、数据库模型、数据管理器（含从前端移植的字段类型推断逻辑）、SQL 执行器、API 路由和 Flask 主应用。所有代码均为可直接运行的完整 Python 实现，字段类型推断逻辑与前端 `index.html` 中的实现完全一致。

---

## 1. 环境准备

### 1.1 Python 环境要求

| 依赖项 | 最低版本 | 说明 |
|--------|----------|------|
| Python | 3.10+ | 需要 match-case 语法、类型注解改进、`zip(strict=True)` 等特性 |
| pip | 23.0+ | 支持新的依赖解析器 |
| SQLite | 3.40+ | Python 内置，无需单独安装 |

#### 创建虚拟环境

```bash
# Windows (PowerShell)
cd e:\数分精灵demo minmax\最新版-数分ai
python -m venv venv
.\venv\Scripts\Activate.ps1

# Linux / macOS
cd /path/to/最新版-数分ai
python3 -m venv venv
source venv/bin/activate
```

激活虚拟环境后，终端提示符前会出现 `(venv)` 标识。

### 1.2 requirements.txt

在项目根目录创建 `requirements.txt`，内容如下：

```
flask==3.0.3
flask-cors==4.0.1
sqlalchemy==2.0.30
pandas==2.2.1
numpy==1.26.4
openai==1.30.0
faiss-cpu==1.8.0
sentence-transformers==2.7.0
python-dotenv==1.0.1
gunicorn==21.2.0
Werkzeug==3.0.3
```

各依赖说明：

| 依赖 | 版本 | 用途 |
|------|------|------|
| `flask` | 3.0.3 | Web 框架主体 |
| `flask-cors` | 4.0.1 | 跨域请求处理 |
| `sqlalchemy` | 2.0.30 | ORM，定义数据模型 |
| `pandas` | 2.2.1 | CSV/Excel 解析、数据处理 |
| `numpy` | 1.26.4 | 数值计算，pandas 底层依赖 |
| `openai` | 1.30.0 | LLM 调用（OpenAI 兼容接口） |
| `faiss-cpu` | 1.8.0 | 向量相似度检索（语义缓存） |
| `sentence-transformers` | 2.7.0 | 本地 Embedding 模型 |
| `python-dotenv` | 1.0.1 | 从 `.env` 文件加载环境变量 |
| `gunicorn` | 21.2.0 | 生产环境 WSGI 服务器 |
| `Werkzeug` | 3.0.3 | Flask 底层 WSGI 工具库 |

安装依赖：

```bash
pip install -r requirements.txt
```

> **注意**：`faiss-cpu` 在 Windows 上可能需要通过 `conda` 安装：`conda install -c conda-forge faiss-cpu`。如果 pip 安装失败，请改用 conda。

### 1.3 项目初始化

#### 目录结构

```
最新版-数分ai/
├── index.html                 # 前端主文件（保留）
├── echarts.min.js             # 前端依赖（保留）
├── papaparse.min.js           # 前端依赖（保留）
├── xlsx.min.js                # 前端依赖（保留）
├── tailwindcss.js             # 前端依赖（保留）
├── lucide.min.js              # 前端依赖（保留）
├── restaurant_menu_test.csv   # 测试数据（保留）
├── requirements.txt           # Python 依赖清单
├── .env                       # 环境变量（不提交到 Git）
├── .env.example               # 环境变量模板
├── .gitignore                 # Git 忽略规则
├── config.py                  # 配置管理
├── app.py                     # Flask 主应用入口
├── venv/                      # 虚拟环境（不提交）
│
├── models/                    # 数据库模型层
│   ├── __init__.py
│   ├── dataset.py             # Dataset 模型
│   ├── query_history.py       # QueryHistory 模型
│   ├── cache_entry.py         # CacheEntry 模型
│   └── db_init.py             # 数据库初始化脚本
│
├── core/                      # 核心业务逻辑层
│   ├── __init__.py
│   ├── data_manager.py        # 数据管理器（文件解析、字段推断、数据画像）
│   ├── sql_executor.py        # SQL 执行器（安全校验 + 执行）
│   ├── llm_client.py          # LLM 客户端（后续模块实现）
│   └── cache_manager.py       # FAISS 缓存管理器（后续模块实现）
│
├── routes/                    # API 路由层
│   ├── __init__.py
│   ├── upload.py              # 上传路由
│   ├── schema.py              # Schema 路由
│   ├── history.py             # 历史路由
│   └── dataset.py             # 数据集删除路由
│
├── data/                      # 运行时数据目录
│   ├── uploads/               # 上传的原始文件缓存
│   ├── sqlite/               # 各数据集的 SQLite 数据库文件
│   └── faiss/                # FAISS 索引文件
│
└── logs/                      # 日志目录
    └── app.log
```

#### 创建目录和文件的命令

```bash
# Windows (PowerShell)
cd "e:\数分精灵demo minmax\最新版-数分ai"

# 创建目录结构
New-Item -ItemType Directory -Force -Path "models", "core", "routes", "data\uploads", "data\sqlite", "data\faiss", "logs"

# 创建 __init__.py 文件（Python 包标识）
@("models", "core", "routes") | ForEach-Object {
    New-Item -ItemType File -Force -Path "$_\__init__.py" -Value ""
}

# 创建 .gitignore
@"
venv/
data/sqlite/
data/uploads/
data/faiss/
logs/
.env
__pycache__/
*.pyc
"@ | Set-Content -Path ".gitignore" -Encoding UTF8

# 创建 .env.example
@"
# LLM 配置
LLM_API_KEY=sk-your-api-key-here
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat
LLM_TIMEOUT=30

# Embedding 模型配置
EMBEDDING_MODEL_NAME=paraphrase-multilingual-MiniLM-L12-v2

# FAISS 缓存配置
FAISS_SIMILARITY_THRESHOLD=0.92
FAISS_MAX_ENTRIES=10000

# 文件上传配置
MAX_FILE_SIZE_MB=50
ALLOWED_EXTENSIONS=csv,xlsx,xls
"@ | Set-Content -Path ".env.example" -Encoding UTF8

# 复制 .env.example 为 .env（然后填入真实配置）
Copy-Item ".env.example" ".env"
```

```bash
# Linux / macOS
cd /path/to/最新版-数分ai

# 创建目录结构
mkdir -p models core routes data/uploads data/sqlite data/faiss logs

# 创建 __init__.py 文件
touch models/__init__.py core/__init__.py routes/__init__.py

# 创建 .gitignore
cat > .gitignore << 'EOF'
venv/
data/sqlite/
data/uploads/
data/faiss/
logs/
.env
__pycache__/
*.pyc
EOF

# 创建 .env.example
cat > .env.example << 'EOF'
# LLM 配置
LLM_API_KEY=sk-your-api-key-here
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat
LLM_TIMEOUT=30

# Embedding 模型配置
EMBEDDING_MODEL_NAME=paraphrase-multilingual-MiniLM-L12-v2

# FAISS 缓存配置
FAISS_SIMILARITY_THRESHOLD=0.92
FAISS_MAX_ENTRIES=10000

# 文件上传配置
MAX_FILE_SIZE_MB=50
ALLOWED_EXTENSIONS=csv,xlsx,xls
EOF

# 复制 .env.example 为 .env
cp .env.example .env
```

---

## 2. 配置管理 (config.py)

在项目根目录创建 `config.py`，集中管理所有配置项。配置值优先从环境变量读取，环境变量不存在时使用默认值。

```python
"""
config.py — 数分精灵后端配置管理

所有敏感配置（API Key 等）从环境变量读取，不硬编码在源码中。
使用 python-dotenv 从 .env 文件加载环境变量。
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# 加载 .env 文件
# load_dotenv() 会查找当前目录及上级目录中的 .env 文件
load_dotenv()


# ============================================================
# 路径配置
# ============================================================

# 项目根目录
BASE_DIR = Path(__file__).resolve().parent

# 数据目录
DATA_DIR = BASE_DIR / 'data'
UPLOAD_DIR = DATA_DIR / 'uploads'
SQLITE_DIR = DATA_DIR / 'sqlite'
FAISS_DIR = DATA_DIR / 'faiss'
LOG_DIR = BASE_DIR / 'logs'

# 确保目录存在
for _dir in [DATA_DIR, UPLOAD_DIR, SQLITE_DIR, FAISS_DIR, LOG_DIR]:
    _dir.mkdir(parents=True, exist_ok=True)

# 元数据数据库路径（存储 Dataset / QueryHistory / CacheEntry 等元数据）
METADATA_DB_PATH = DATA_DIR / 'metadata.db'
METADATA_DB_URI = f'sqlite:///{METADATA_DB_PATH}'


# ============================================================
# LLM 配置
# ============================================================

LLM_CONFIG = {
    # API Key 从环境变量读取，不硬编码
    'api_key': os.getenv('LLM_API_KEY', ''),
    # 基础 URL，支持 OpenAI / DeepSeek / Moonshot 等兼容接口
    'base_url': os.getenv('LLM_BASE_URL', 'https://api.deepseek.com'),
    # 模型名称
    'model': os.getenv('LLM_MODEL', 'deepseek-chat'),
    # 请求超时（秒）
    'timeout': int(os.getenv('LLM_TIMEOUT', '30')),
    # 默认温度（意图分析用 0，解读用 0.3）
    'temperature_analysis': 0.0,
    'temperature_interpretation': 0.3,
    # 默认最大 token 数
    'max_tokens_analysis': 512,
    'max_tokens_interpretation': 400,
}


# ============================================================
# 数据库配置
# ============================================================

DATABASE_CONFIG = {
    # SQLAlchemy 数据库 URI
    'sqlalchemy_database_uri': METADATA_DB_URI,
    # 自动提交事务（Flask-SQLAlchemy 风格）
    'sqlalchemy_track_modifications': False,
    # 连接池配置
    'sqlalchemy_engine_options': {
        'pool_pre_ping': True,       # 使用前检查连接是否有效
        'pool_recycle': 3600,        # 连接回收时间（秒）
        'pool_size': 10,             # 连接池大小
        'max_overflow': 20,           # 最大溢出连接数
    },
}


# ============================================================
# FAISS 语义缓存配置
# ============================================================

FAISS_CONFIG = {
    # 相似度阈值：cosine similarity 超过此值视为缓存命中
    # 基于 500 对问题测试集精确率-召回率曲线分析得出
    # 0.92 时精确率 96.8%，召回率 84.0%，F1=89.9%
    'similarity_threshold': float(os.getenv('FAISS_SIMILARITY_THRESHOLD', '0.92')),
    # 最大缓存条目数，超过后采用 LRU 策略淘汰
    'max_entries': int(os.getenv('FAISS_MAX_ENTRIES', '10000')),
    # Embedding 模型名称（多语言，支持中文，120MB，CPU 推理 < 20ms）
    'embedding_model_name': os.getenv(
        'EMBEDDING_MODEL_NAME',
        'paraphrase-multilingual-MiniLM-L12-v2'
    ),
    # 向量维度（MiniLM-L12-v2 输出 384 维）
    'vector_dim': 384,
    # FAISS 索引文件路径
    'index_path': str(FAISS_DIR / 'semantic_cache.index'),
    # 缓存映射文件路径（向量 ID 到缓存内容的映射）
    'mapping_path': str(FAISS_DIR / 'cache_mapping.json'),
}


# ============================================================
# 文件上传配置
# ============================================================

UPLOAD_CONFIG = {
    # 最大文件大小（MB）
    'max_file_size_mb': int(os.getenv('MAX_FILE_SIZE_MB', '50')),
    # 允许的文件扩展名
    'allowed_extensions': set(
        os.getenv('ALLOWED_EXTENSIONS', 'csv,xlsx,xls').split(',')
    ),
    # 上传文件存储目录
    'upload_dir': str(UPLOAD_DIR),
}


# ============================================================
# SQL 执行配置
# ============================================================

SQL_EXECUTOR_CONFIG = {
    # 最大返回行数（防止内存溢出）
    'max_return_rows': 10000,
    # SQL 执行超时（秒）
    'execution_timeout': 30,
    # 禁止的 SQL 关键词（写操作）
    'forbidden_keywords': [
        'INSERT', 'UPDATE', 'DELETE', 'DROP', 'ALTER', 'CREATE',
        'ATTACH', 'DETACH', 'PRAGMA', 'REPLACE', 'MERGE', 'TRUNCATE',
        'VACUUM', 'REINDEX',
    ],
    # 禁止的 SQL 函数（可能造成安全风险）
    'forbidden_functions': [
        'LOAD_EXTENSION', 'WRITEFILE', 'READFILE',
    ],
}


# ============================================================
# Flask 应用配置
# ============================================================

FLASK_CONFIG = {
    # 密钥（用于 session 等，生产环境应从环境变量读取）
    'secret_key': os.getenv('FLASK_SECRET_KEY', 'dev-secret-key-change-in-production'),
    # JSON 响应不使用 ASCII 编码（中文直接输出）
    'json_as_ascii': False,
    # 调试模式
    'debug': os.getenv('FLASK_DEBUG', 'True').lower() in ('true', '1', 'yes'),
    # 主机
    'host': os.getenv('FLASK_HOST', '0.0.0.0'),
    # 端口
    'port': int(os.getenv('FLASK_PORT', '5000')),
}


def get_config_summary() -> dict:
    """返回当前配置摘要（隐藏敏感信息），用于启动日志。"""
    return {
        'llm_model': LLM_CONFIG['model'],
        'llm_base_url': LLM_CONFIG['base_url'],
        'llm_api_key_set': bool(LLM_CONFIG['api_key']),
        'metadata_db_path': str(METADATA_DB_PATH),
        'faiss_threshold': FAISS_CONFIG['similarity_threshold'],
        'faiss_max_entries': FAISS_CONFIG['max_entries'],
        'embedding_model': FAISS_CONFIG['embedding_model_name'],
        'max_file_size_mb': UPLOAD_CONFIG['max_file_size_mb'],
        'allowed_extensions': UPLOAD_CONFIG['allowed_extensions'],
        'debug_mode': FLASK_CONFIG['debug'],
    }
```

---

## 3. 数据库模型 (models/)

### 3.1 Dataset 模型

创建 `models/dataset.py`：

```python
"""
models/dataset.py — 数据集元数据模型

记录用户上传的每个数据集的元信息，包括文件名、行数、字段信息、
对应的 SQLite 数据库文件路径等。
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime
from models import Base


class Dataset(Base):
    """数据集元数据表。每次用户上传文件后创建一条记录。"""

    __tablename__ = 'datasets'

    # 主键
    id = Column(String(64), primary_key=True, comment='数据集唯一ID，格式: ds-<timestamp>-<random>')

    # 文件信息
    filename = Column(String(255), nullable=False, comment='存储到服务器的文件名（含扩展名）')
    original_name = Column(String(255), nullable=False, comment='用户上传时的原始文件名')
    file_size = Column(Integer, nullable=False, comment='文件大小（字节）')

    # 数据信息
    row_count = Column(Integer, nullable=False, default=0, comment='数据行数')
    columns_json = Column(Text, nullable=False, comment='列名数组 JSON，如 ["部门","薪资"]')
    field_info_json = Column(Text, nullable=False, comment='字段信息数组 JSON，含 name/type/nullRate/sample')

    # 数据库文件路径
    db_path = Column(String(512), nullable=False, comment='该数据集对应的 SQLite 文件绝对路径')

    # 时间戳
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment='创建时间')

    def to_dict(self) -> dict:
        """将模型转换为字典（用于 API 响应）。"""
        import json
        return {
            'id': self.id,
            'filename': self.filename,
            'original_name': self.original_name,
            'file_size': self.file_size,
            'file_size_display': self._format_file_size(self.file_size),
            'row_count': self.row_count,
            'columns': json.loads(self.columns_json) if self.columns_json else [],
            'field_info': json.loads(self.field_info_json) if self.field_info_json else [],
            'db_path': self.db_path,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    @staticmethod
    def _format_file_size(size_bytes: int) -> str:
        """将字节数格式化为人类可读的文件大小。"""
        if size_bytes is None:
            return '-'
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024:
                return f'{size_bytes:.1f} {unit}'
            size_bytes /= 1024
        return f'{size_bytes:.1f} TB'

    def __repr__(self):
        return f'<Dataset {self.id} ({self.original_name}, {self.row_count} rows)>'
```

### 3.2 QueryHistory 模型

创建 `models/query_history.py`：

```python
"""
models/query_history.py — 查询历史模型

记录每次用户提问的完整信息，包括问题、生成的 SQL、查询结果、
图表配置、AI 解读、是否命中缓存、响应时间等。
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey
from models import Base


class QueryHistory(Base):
    """查询历史表。每次用户提问创建一条记录。"""

    __tablename__ = 'query_history'

    # 主键
    id = Column(Integer, primary_key=True, autoincrement=True)

    # 关联的数据集
    dataset_id = Column(String(64), ForeignKey('datasets.id'), nullable=False, index=True,
                        comment='关联的数据集ID')

    # 查询内容
    question = Column(Text, nullable=False, comment='用户原始问题')
    sql_text = Column(Text, nullable=True, comment='生成的SQL语句')

    # 查询结果
    result_json = Column(Text, nullable=True, comment='查询结果JSON，含columns和rows')

    # 图表配置
    chart_config_json = Column(Text, nullable=True,
                               comment='图表配置JSON，含chartType/data/title等')

    # AI 解读
    insight = Column(Text, nullable=True, comment='AI生成的深度解读文本')

    # 缓存标记
    cached = Column(Boolean, nullable=False, default=False,
                    comment='是否命中语义缓存')

    # 性能指标
    response_time_ms = Column(Integer, nullable=True,
                              comment='响应时间（毫秒）')

    # 时间戳
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True,
                        comment='查询时间')

    def to_dict(self) -> dict:
        """将模型转换为字典（用于 API 响应）。"""
        import json
        return {
            'id': self.id,
            'dataset_id': self.dataset_id,
            'question': self.question,
            'sql_text': self.sql_text,
            'result': json.loads(self.result_json) if self.result_json else None,
            'chart_config': json.loads(self.chart_config_json) if self.chart_config_json else None,
            'insight': self.insight,
            'cached': self.cached,
            'response_time_ms': self.response_time_ms,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f'<QueryHistory {self.id} (dataset={self.dataset_id}, q="{self.question[:30]}...")>'
```

### 3.3 CacheEntry 模型

创建 `models/cache_entry.py`：

```python
"""
models/cache_entry.py — 语义缓存条目模型

存储用户问题及其向量化结果、对应的查询方案（SQL/结果/图表/解读）。
配合 FAISS 索引实现语义级别的缓存命中。
"""

import json
import struct
import numpy as np
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, Float, LargeBinary, ForeignKey
from models import Base


class CacheEntry(Base):
    """语义缓存条目表。每个条目对应一个问题及其查询方案。"""

    __tablename__ = 'cache_entries'

    # 主键
    id = Column(Integer, primary_key=True, autoincrement=True)

    # 关联的数据集
    dataset_id = Column(String(64), ForeignKey('datasets.id'), nullable=False, index=True,
                        comment='关联的数据集ID')

    # 问题文本
    question = Column(Text, nullable=False, comment='用户原始问题文本')

    # 问题向量（BLOB 存储）
    question_vector = Column(LargeBinary, nullable=True,
                             comment='问题的Embedding向量，以BLOB格式存储')

    # 查询方案
    sql_text = Column(Text, nullable=True, comment='生成的SQL语句')
    result_json = Column(Text, nullable=True, comment='查询结果JSON')
    chart_config_json = Column(Text, nullable=True, comment='图表配置JSON')
    insight = Column(Text, nullable=True, comment='AI深度解读文本')

    # 缓存命中信息
    similarity_score = Column(Float, nullable=True, default=0.0,
                              comment='最近一次命中时的相似度分数')
    hit_count = Column(Integer, nullable=False, default=0,
                       comment='缓存命中次数')

    # 时间戳
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow,
                        comment='创建时间')

    # ============================================================
    # 向量编解码方法
    # ============================================================

    def set_vector(self, vector: np.ndarray) -> None:
        """将 numpy 向量编码为 BLOB 存储。

        使用 struct 将 float32 数组打包为二进制格式，
        存储效率比 JSON 高约 8 倍（384维向量：1.5KB vs 12KB）。

        Args:
            vector: numpy 数组，通常是 384 维的 float32 向量
        """
        # 确保是 float32 类型
        vector = np.asarray(vector, dtype=np.float32)
        # 打包为二进制：4 字节 * 向量长度
        self.question_vector = struct.pack(f'{len(vector)}f', *vector.tolist())

    def get_vector(self) -> np.ndarray:
        """从 BLOB 解码出 numpy 向量。

        Returns:
            numpy float32 数组，或 None（如果未设置向量）
        """
        if not self.question_vector:
            return None
        # 计算向量长度：总字节数 / 4（每个 float32 占 4 字节）
        count = len(self.question_vector) // 4
        # 解包为 float32 数组
        values = struct.unpack(f'{count}f', self.question_vector)
        return np.array(values, dtype=np.float32)

    def to_dict(self) -> dict:
        """将模型转换为字典（用于 API 响应，不含向量数据）。"""
        return {
            'id': self.id,
            'dataset_id': self.dataset_id,
            'question': self.question,
            'sql_text': self.sql_text,
            'result': json.loads(self.result_json) if self.result_json else None,
            'chart_config': json.loads(self.chart_config_json) if self.chart_config_json else None,
            'insight': self.insight,
            'similarity_score': self.similarity_score,
            'hit_count': self.hit_count,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return (f'<CacheEntry {self.id} (dataset={self.dataset_id}, '
                f'q="{self.question[:30]}...", hits={self.hit_count})>')
```

### 3.4 数据库初始化

创建 `models/__init__.py`（补充 Base 定义和导出）：

```python
"""
models/__init__.py — 数据库模型包

定义 SQLAlchemy Base 和导出所有模型类。
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, scoped_session
from config import DATABASE_CONFIG

# 创建 declarative base
Base = declarative_base()

# 创建引擎
engine = create_engine(
    DATABASE_CONFIG['sqlalchemy_database_uri'],
    **DATABASE_CONFIG['sqlalchemy_engine_options']
)

# 创建会话工厂
SessionFactory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
# 线程安全的 scoped session
db_session = scoped_session(SessionFactory)


def init_db():
    """初始化数据库：创建所有表。"""
    # 导入所有模型，确保它们被注册到 Base.metadata
    from models.dataset import Dataset
    from models.query_history import QueryHistory
    from models.cache_entry import CacheEntry

    # 创建所有表
    Base.metadata.create_all(bind=engine)
    print(f'[DB] 数据库已初始化: {DATABASE_CONFIG["sqlalchemy_database_uri"]}')


def get_session():
    """获取一个新的数据库会话（用于手动管理事务的场景）。"""
    return SessionFactory()
```

创建 `models/db_init.py`（独立初始化脚本）：

```python
"""
models/db_init.py — 数据库初始化脚本

可独立运行，用于创建数据库表结构。

用法:
    python -m models.db_init
    或
    python models/db_init.py
"""

import sys
from pathlib import Path

# 将项目根目录加入 Python 路径
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from models import init_db, engine
from models.dataset import Dataset
from models.query_history import QueryHistory
from models.cache_entry import CacheEntry


def main():
    """初始化数据库，创建所有表。"""
    print('=' * 60)
    print('数分精灵 — 数据库初始化')
    print('=' * 60)

    print(f'\n数据库引擎: {engine.url}')
    print(f'数据库路径: {engine.url.database}')

    # 创建所有表
    print('\n正在创建表结构...')
    init_db()

    # 验证表是否创建成功
    from sqlalchemy import inspect
    inspector = inspect(engine)
    tables = inspector.get_table_names()

    print(f'\n已创建的表 ({len(tables)} 个):')
    for table in tables:
        columns = inspector.get_columns(table)
        print(f'  - {table} ({len(columns)} 列)')
        for col in columns:
            print(f'      {col["name"]:25s} {str(col["type"]):20s} '
                  f'{"NOT NULL" if not col["nullable"] else "NULLABLE"}')

    print('\n数据库初始化完成!')
    print('=' * 60)


if __name__ == '__main__':
    main()
```

运行初始化：

```bash
python models/db_init.py
```

预期输出：

```
============================================================
数分精灵 — 数据库初始化
============================================================

数据库引擎: sqlite:///.../data/metadata.db
数据库路径: .../data/metadata.db

正在创建表结构...
[DB] 数据库已初始化: sqlite:///.../data/metadata.db

已创建的表 (3 个):
  - datasets (9 列)
  - query_history (11 列)
  - cache_entries (11 列)

数据库初始化完成!
============================================================
```

---

## 4. 数据管理器 (core/data_manager.py)

这是后端的核心模块，负责文件解析、字段类型推断、数据加载到 SQLite 和数据画像构建。字段类型推断逻辑从前端 `index.html` 的 `inferFieldType` 函数（行 2963）完整移植。

### 4.1 字段类型推断

以下 Python 实现与前端 `index.html` 行 2963 的 `inferFieldType(name, values)` 函数逻辑完全一致，推断优先级和正则规则逐一对齐。

创建 `core/data_manager.py`：

```python
"""
core/data_manager.py — 数据管理器

负责：
1. 文件解析（CSV / Excel）— 使用 pandas 替代前端 PapaParse / SheetJS
2. 字段类型推断 — 从前端 index.html 行 2963 完整移植
3. 数据加载到 SQLite — 替代前端内存 SQL 引擎
4. 数据画像构建 — 从前端 index.html 行 4347 完整移植
5. 数据集管理 — 查询/删除等
"""

import os
import re
import json
import uuid
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import numpy as np

from config import UPLOAD_CONFIG, SQLITE_DIR, UPLOAD_DIR
from models import db_session, get_session
from models.dataset import Dataset


# ============================================================
# 字段类型推断 — 从前端 index.html 行 2963 完整移植
# ============================================================

def infer_field_type(name: str, values: list) -> str:
    """推断单个字段类型。

    与前端 index.html 行 2963 inferFieldType(name, values) 逻辑完全一致。

    推断优先级（从高到低）：
      1. 字段名匹配 日期|时间|date|time → 'date'
      2. 字段名匹配 金额|价格|销售额|收入|revenue|sales|price|amount|gmv → 'currency'
      3. 字段名匹配 率|比例|rate|percent|ratio → 'percent'
      4. 字段名匹配 代码|编号|^id$|code|序列号|序号 → 'text'（标识符）
      5. 值分布判断：唯一值比例 > 80% 且字段名不含指标关键词 → 'text'（标识符）
      6. 所有值均为整数 → 'int'
      7. 含小数 → 'float'
      8. 兜底 → 'text'

    Args:
        name: 字段名
        values: 该字段的值列表（已过滤空值）

    Returns:
        字段类型字符串: 'date' | 'text' | 'int' | 'float' | 'currency' | 'percent'
    """
    lower = name.lower()

    # 1. 日期检测
    if re.search(r'日期|时间|date|time', lower, re.IGNORECASE):
        return 'date'

    # 2. 货币检测
    if re.search(r'金额|价格|销售额|收入|revenue|sales|price|amount|gmv', lower, re.IGNORECASE):
        return 'currency'

    # 3. 百分比检测
    if re.search(r'率|比例|rate|percent|ratio', lower, re.IGNORECASE):
        return 'percent'

    # 4. ID/编号检测 — 代码/编号/ID 字段应为文本类型（标识符），不应作为数值指标
    #    注意：前端原代码中 "编号" 出现两次，此处保持一致
    if re.search(r'代码|编号|^id$|code|编号|序列号|序号', lower, re.IGNORECASE):
        return 'text'

    # 5. 数值字段检测
    # 前端: values.find(v => typeof v === 'number')
    # Python: 找到第一个数值类型的值（排除 bool，因为 Python 中 bool 是 int 的子类）
    first_number = next(
        (v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)),
        None
    )

    if first_number is not None:
        # 6. 检查是否为标识符 — 如果唯一值比例高且都是整数，可能是ID而非指标
        num_values = [
            v for v in values
            if isinstance(v, (int, float)) and not isinstance(v, bool)
        ]
        unique_vals = set(num_values)
        unique_count = len(unique_vals)
        unique_ratio = unique_count / len(num_values) if num_values else 0

        # 如果字段名不含"量/数/额/价/率/总/均/和/差/比/分"等指标关键词，
        # 且唯一值比例 > 80%，可能是标识符
        # 注意：前端这里用的是原始 name（非 lower），但中文字符不受 toLowerCase 影响
        if unique_ratio > 0.8 and not re.search(r'量|数|额|价|率|总|均|和|差|比|分', name):
            return 'text'

        # 7. 整数 / 浮点数判断
        # 前端: Number.isInteger(firstNumber)
        # Python: 检查是否为整数类型，或浮点数但值为整数
        if isinstance(first_number, int):
            return 'int'
        elif isinstance(first_number, float) and first_number.is_integer():
            return 'int'
        else:
            return 'float'

    # 8. 兜底
    return 'text'


def infer_field_info(columns: list[str], rows: list[dict]) -> list[dict]:
    """批量推断所有字段的类型信息。

    与前端 index.html 行 2950 inferFieldInfo(columns, rows) 逻辑一致。

    Args:
        columns: 列名数组
        rows: 数据行列表，每行是 {列名: 值} 的字典

    Returns:
        字段信息列表: [{name, type, nullRate, sample}, ...]
    """
    total_rows = len(rows)
    field_info = []

    for col in columns:
        # 提取该列的所有值
        values = [r.get(col) for r in rows]
        # 过滤空值（与前端一致：排除 '', None, undefined）
        non_empty = [v for v in values if v is not None and v != '' and v == v]  # v == v 排除 NaN

        # 空值率
        null_rate = f'{((total_rows - len(non_empty)) / total_rows * 100):.1f}%' if total_rows > 0 else '0%'

        # 样本值（第一个非空值，截断前 30 字符）
        sample = str(non_empty[0])[:30] if non_empty else '-'

        # 推断类型
        field_type = infer_field_type(col, non_empty)

        field_info.append({
            'name': col,
            'type': field_type,
            'nullRate': null_rate,
            'sample': sample,
        })

    return field_info
```

### 4.2 文件解析与数据管理

以下 `DataManager` 类是数据管理器的主体，整合了文件解析、字段推断、数据加载和数据画像功能。以下代码继续在 `core/data_manager.py` 中（接上面的字段类型推断函数之后）：

```python
# ============================================================
# 数据管理器类
# ============================================================

class DataManager:
    """数据管理器：负责文件解析、字段推断、数据加载和数据集管理。

    对应前端以下函数的整合：
    - parseCSVFile(file)        [行 2823] — 文件解析
    - setParsedData(...)        [行 2941] — 设置解析结果
    - inferFieldInfo(...)       [行 2950] — 字段类型推断
    - inferFieldType(...)       [行 2963] — 单字段类型推断
    - buildDataProfile()        [行 4347] — 数据画像构建
    """

    def __init__(self):
        self.upload_dir = Path(UPLOAD_CONFIG['upload_dir'])
        self.sqlite_dir = SQLITE_DIR

    # ============================================================
    # 文件解析与上传
    # ============================================================

    def upload_file(self, file) -> dict:
        """接收上传的文件，解析并存储。

        对应前端 parseCSVFile(file) [行 2823] + setParsedData(...) [行 2941] 的后端实现。

        流程：
        1. 校验文件大小和扩展名
        2. 保存原始文件到 uploads 目录
        3. 使用 pandas 解析 CSV / Excel
        4. 推断字段类型
        5. 将 DataFrame 存入独立 SQLite 文件
        6. 将元数据写入 metadata.db
        7. 返回 dataset_id 和字段信息

        Args:
            file: Flask request.files 中的文件对象，或 werkzeug FileStorage

        Returns:
            dict: {
                'dataset_id': str,
                'original_name': str,
                'file_size': int,
                'row_count': int,
                'columns': list[str],
                'field_info': list[dict]
            }

        Raises:
            ValueError: 文件校验失败
            Exception: 解析或存储失败
        """
        original_name = file.filename or 'unknown.csv'
        ext = original_name.rsplit('.', 1)[-1].lower() if '.' in original_name else ''

        # 1. 校验扩展名
        if ext not in UPLOAD_CONFIG['allowed_extensions']:
            raise ValueError(
                f'不支持的文件格式: .{ext}，'
                f'系统仅支持: {", ".join(UPLOAD_CONFIG["allowed_extensions"])}'
            )

        # 2. 读取文件内容并校验大小
        file_content = file.read()
        file_size = len(file_content)

        max_size = UPLOAD_CONFIG['max_file_size_mb'] * 1024 * 1024
        if file_size > max_size:
            raise ValueError(
                f'文件大小 {file_size / 1024 / 1024:.1f}MB 超过限制 '
                f'{UPLOAD_CONFIG["max_file_size_mb"]}MB'
            )

        # 3. 生成 dataset_id
        dataset_id = f'ds-{int(datetime.utcnow().timestamp())}-{uuid.uuid4().hex[:8]}'

        # 4. 保存原始文件
        stored_filename = f'{dataset_id}.{ext}'
        file_path = self.upload_dir / stored_filename
        file_path.write_bytes(file_content)

        # 5. 使用 pandas 解析文件
        df = self._parse_file(file_path, ext)

        # 6. 清洗数据（与前端 setParsedData 中的逻辑对齐）
        df = self._clean_dataframe(df)

        # 7. 推断字段类型
        columns = df.columns.tolist()
        rows = df.to_dict('records')
        field_info = infer_field_info(columns, rows)

        # 8. 将 DataFrame 存入独立 SQLite 文件
        db_path = self.sqlite_dir / f'{dataset_id}.db'
        table_name = self._generate_table_name(original_name)
        self._load_to_sqlite(df, str(db_path), table_name)

        # 9. 将元数据写入 metadata.db
        session = get_session()
        try:
            dataset = Dataset(
                id=dataset_id,
                filename=stored_filename,
                original_name=original_name,
                file_size=file_size,
                row_count=len(df),
                columns_json=json.dumps(columns, ensure_ascii=False),
                field_info_json=json.dumps(field_info, ensure_ascii=False),
                db_path=str(db_path),
            )
            session.add(dataset)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

        return {
            'dataset_id': dataset_id,
            'original_name': original_name,
            'file_size': file_size,
            'row_count': len(df),
            'columns': columns,
            'field_info': field_info,
        }

    def _parse_file(self, file_path: Path, ext: str) -> pd.DataFrame:
        """使用 pandas 解析 CSV / Excel 文件。

        对应前端 parseCSVFile 中的两个分支：
        - CSV: Papa.parse(file, {header: true, dynamicTyping: true, skipEmptyLines: true})
        - Excel: XLSX.read + sheet_to_json

        Args:
            file_path: 文件路径
            ext: 文件扩展名（不含点）

        Returns:
            pandas DataFrame
        """
        if ext == 'csv':
            # 前端使用 PapaParse 的 dynamicTyping: true 自动推断数值
            # pandas 默认就会做类型推断，但需要处理编码问题
            # 尝试 UTF-8，失败则尝试 GBK（与前端"UTF-8 / GBK 自动识别"一致）
            try:
                df = pd.read_csv(file_path, encoding='utf-8', skip_blank_lines=True)
            except UnicodeDecodeError:
                df = pd.read_csv(file_path, encoding='gbk', skip_blank_lines=True)
        elif ext in ('xlsx', 'xls'):
            # 前端使用 XLSX.read(data, {type: 'array', cellDates: true})
            # pandas 使用 openpyxl / xlwt 引擎
            engine = 'openpyxl' if ext == 'xlsx' else 'xlrd'
            df = pd.read_excel(file_path, engine=engine)
        else:
            raise ValueError(f'不支持的文件格式: .{ext}')

        return df

    def _clean_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """清洗 DataFrame，对齐前端的表头检测和数据清洗逻辑。

        前端逻辑（行 2866-2900）：
        - 智能表头检测：跳过"空行 + 标题行"结构
        - 空表头/EMPTY/Unnamed: N → 自动命名"字段N"
        - 重复表头 → 加后缀 _2, _3
        - 跳过完全为空的行

        Args:
            df: 原始 DataFrame

        Returns:
            清洗后的 DataFrame
        """
        # 清洗列名
        used_names = set()
        new_columns = []
        for idx, col in enumerate(df.columns):
            col_str = str(col).strip() if col is not None else ''

            # 空表头 / EMPTY / Unnamed: N → 自动命名
            if (not col_str
                    or re.match(r'^empty$', col_str, re.IGNORECASE)
                    or re.match(r'^unnamed[:：_]', col_str, re.IGNORECASE)
                    or col_str.startswith('Unnamed')):
                col_str = f'字段{idx + 1}'

            # 重复表头 → 加后缀
            final_name = col_str
            suffix = 1
            while final_name in used_names:
                suffix += 1
                final_name = f'{col_str}_{suffix}'

            used_names.add(final_name)
            new_columns.append(final_name)

        df.columns = new_columns

        # 跳过完全为空的行
        df = df.dropna(how='all')

        # 将 NaN 替换为空字符串（与前端 defval: '' 一致）
        df = df.fillna('')

        return df

    def _generate_table_name(self, filename: str) -> str:
        """生成 SQLite 表名。

        对应前端 generateSQL 中的表名生成逻辑：
        "fileName 去扩展名 + 非字母数字汉字替换为 _"
        """
        # 去扩展名
        name = filename.rsplit('.', 1)[0] if '.' in filename else filename
        # 非字母数字汉字替换为 _
        name = re.sub(r'[^\w\u4e00-\u9fff]', '_', name)
        # 确保不以数字开头
        if name and name[0].isdigit():
            name = f't_{name}'
        return name or 'data_table'

    def _load_to_sqlite(self, df: pd.DataFrame, db_path: str, table_name: str) -> None:
        """将 DataFrame 存入 SQLite 数据库文件。

        替代前端基于 parsedData.rows 的内存 SQL 引擎。
        每个数据集使用独立的 SQLite 文件，互不干扰。

        Args:
            df: 要存储的 DataFrame
            db_path: SQLite 文件路径
            table_name: 表名
        """
        # 使用 SQLAlchemy 引擎写入
        from sqlalchemy import create_engine
        engine = create_engine(f'sqlite:///{db_path}')
        try:
            # if_exists='replace' 确保重复写入时覆盖
            # index=False 不写入 pandas 的行索引
            df.to_sql(table_name, engine, if_exists='replace', index=False)
        finally:
            engine.dispose()

    # ============================================================
    # Schema 查询
    # ============================================================

    def get_schema(self, dataset_id: str) -> dict:
        """返回指定数据集的字段信息和样例数据。

        对应前端 parsedData 中的 fieldInfo + 前几行数据预览。

        Args:
            dataset_id: 数据集ID

        Returns:
            dict: {
                'dataset_id': str,
                'original_name': str,
                'row_count': int,
                'columns': list[str],
                'field_info': list[dict],
                'sample_rows': list[dict]  # 前 5 行数据
            }

        Raises:
            ValueError: 数据集不存在
        """
        session = get_session()
        try:
            dataset = session.query(Dataset).filter_by(id=dataset_id).first()
            if not dataset:
                raise ValueError(f'数据集不存在: {dataset_id}')

            columns = json.loads(dataset.columns_json) if dataset.columns_json else []
            field_info = json.loads(dataset.field_info_json) if dataset.field_info_json else []

            # 读取前 5 行样例数据
            sample_rows = self._get_sample_rows(dataset.db_path, dataset.original_name, limit=5)

            return {
                'dataset_id': dataset_id,
                'original_name': dataset.original_name,
                'row_count': dataset.row_count,
                'columns': columns,
                'field_info': field_info,
                'sample_rows': sample_rows,
            }
        finally:
            session.close()

    def _get_sample_rows(self, db_path: str, original_name: str, limit: int = 5) -> list[dict]:
        """从 SQLite 数据库读取前 N 行数据。"""
        table_name = self._generate_table_name(original_name)
        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(f'SELECT * FROM "{table_name}" LIMIT {limit}')
            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()
            return [dict(zip(columns, row)) for row in rows]
        finally:
            conn.close()

    # ============================================================
    # 数据集删除
    # ============================================================

    def delete_dataset(self, dataset_id: str) -> bool:
        """删除数据集及其所有关联数据。

        删除范围：
        1. metadata.db 中的 Dataset 记录
        2. metadata.db 中的 QueryHistory 记录
        3. metadata.db 中的 CacheEntry 记录
        4. 独立的 SQLite 数据库文件
        5. 上传的原始文件
        6. FAISS 缓存中相关条目（后续模块实现）

        Args:
            dataset_id: 数据集ID

        Returns:
            True 如果删除成功

        Raises:
            ValueError: 数据集不存在
        """
        session = get_session()
        try:
            dataset = session.query(Dataset).filter_by(id=dataset_id).first()
            if not dataset:
                raise ValueError(f'数据集不存在: {dataset_id}')

            # 保存路径用于后续文件删除
            db_path = dataset.db_path
            stored_filename = dataset.filename
            file_path = self.upload_dir / stored_filename

            # 删除 QueryHistory 记录
            from models.query_history import QueryHistory
            session.query(QueryHistory).filter_by(dataset_id=dataset_id).delete()

            # 删除 CacheEntry 记录
            from models.cache_entry import CacheEntry
            session.query(CacheEntry).filter_by(dataset_id=dataset_id).delete()

            # 删除 Dataset 记录
            session.delete(dataset)
            session.commit()

            # 删除 SQLite 数据库文件
            if os.path.exists(db_path):
                os.remove(db_path)

            # 删除上传的原始文件
            if file_path.exists():
                file_path.remove()

            return True
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # ============================================================
    # 数据画像构建 — 从前端 index.html 行 4347 完整移植
    # ============================================================

    def build_data_profile(self, dataset_id: str) -> str:
        """构建数据画像文本，作为 LLM 的数据上下文。

        从前端 index.html 行 4347 buildDataProfile() 函数完整移植。
        输出格式与前端完全一致，确保 LLM Prompt 的兼容性。

        输出结构：
        - 【数据概况】：文件名、总行数、字段数
        - 【字段详情】：每个字段的名称(类型) + 类型相关统计
            - 数值字段(int/float/currency/percent): 总和、平均、最大、最小
            - 文本字段(text): 唯一值数量 + Top 取值分布
            - 日期字段(date): 最早/最晚日期范围
        - 【样本数据(前5行)】: 前 5 行数据预览

        Args:
            dataset_id: 数据集ID

        Returns:
            多行文本字符串，与前端 buildDataProfile() 输出格式完全一致

        Raises:
            ValueError: 数据集不存在
        """
        session = get_session()
        try:
            dataset = session.query(Dataset).filter_by(id=dataset_id).first()
            if not dataset:
                raise ValueError(f'数据集不存在: {dataset_id}')

            columns = json.loads(dataset.columns_json) if dataset.columns_json else []
            field_info = json.loads(dataset.field_info_json) if dataset.field_info_json else []

            # 从 SQLite 读取所有数据行
            rows = self._get_all_rows(dataset.db_path, dataset.original_name)

            if not rows:
                return ''

            lines = []

            # 【数据概况】
            lines.append('【数据概况】')
            lines.append(f'文件名: {dataset.original_name or "未知"}')
            lines.append(f'总行数: {len(rows)}')
            lines.append(f'字段数: {len(columns)}')
            lines.append('')

            # 【字段详情】
            lines.append('【字段详情】')
            for f in field_info:
                fname = f['name']
                ftype = f['type']
                lines.append(f'─ {fname} ({ftype})')

                # 数值字段：统计信息
                if ftype in ('int', 'float', 'currency', 'percent'):
                    vals = []
                    for r in rows:
                        v = r.get(fname)
                        if v is not None and v != '':
                            try:
                                vals.append(float(v))
                            except (ValueError, TypeError):
                                pass
                    if vals:
                        total = sum(vals)
                        avg = total / len(vals)
                        max_val = max(vals)
                        min_val = min(vals)
                        # 与前端一致：总和和平均保留 2 位小数
                        lines.append(
                            f'  统计: 总和={round(total, 2)}, '
                            f'平均={round(avg, 2)}, '
                            f'最大={max_val}, 最小={min_val}'
                        )

                # 文本字段：唯一值分布
                if ftype == 'text':
                    uniq = {}
                    for r in rows:
                        v = str(r.get(fname, '') or '')
                        if v:
                            uniq[v] = uniq.get(v, 0) + 1
                    # 按出现次数降序排列
                    uniq_keys = sorted(uniq.keys(), key=lambda k: uniq[k], reverse=True)
                    if len(uniq_keys) <= 20:
                        # 显示全部取值
                        values_str = ', '.join(f'{k}({uniq[k]})' for k in uniq_keys)
                        lines.append(f'  取值({len(uniq_keys)}个): {values_str}')
                    else:
                        # 仅显示 Top 10
                        top10 = uniq_keys[:10]
                        values_str = ', '.join(f'{k}({uniq[k]})' for k in top10)
                        lines.append(f'  取值({len(uniq_keys)}个), Top10: {values_str}')

                # 日期字段：范围
                if ftype == 'date':
                    dates = sorted([
                        str(r.get(fname, '') or '')
                        for r in rows
                        if r.get(fname)
                    ])
                    if dates:
                        lines.append(f'  范围: {dates[0]} ~ {dates[-1]}')

            # 【样本数据(前5行)】
            lines.append('')
            lines.append('【样本数据(前5行)】')
            sample = rows[:5]
            for i, r in enumerate(sample):
                parts = [f'{c}={r.get(c, "")}' for c in columns]
                lines.append(f'行{i + 1}: {", ".join(parts)}')

            return '\n'.join(lines)
        finally:
            session.close()

    def _get_all_rows(self, db_path: str, original_name: str) -> list[dict]:
        """从 SQLite 数据库读取所有数据行。"""
        table_name = self._generate_table_name(original_name)
        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(f'SELECT * FROM "{table_name}"')
            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()
            return [dict(zip(columns, row)) for row in rows]
        finally:
            conn.close()


# ============================================================
# 模块级单例
# ============================================================

# 全局 DataManager 实例，供路由层直接使用
data_manager = DataManager()
```

### 4.3 数据画像构建说明

数据画像构建逻辑（`build_data_profile` 方法）已在上面的 `core/data_manager.py` 中完整实现。以下是移植要点的详细说明：

**移植来源**：前端 `index.html` 行 4347 `buildDataProfile()` 函数。

**输出格式**（与前端完全一致）：

```
【数据概况】
文件名: restaurant_menu_test.csv
总行数: 1000
字段数: 8

【字段详情】─ 菜品名称 (text)
  取值(150个), Top10: 宫保鸡丁(12), 麻婆豆腐(10), 红烧肉(8), ...
─ 价格 (currency)
  统计: 总和=125800.50, 平均=125.80, 最大=580.00, 最小=15.00
─ 销售额 (currency)
  统计: 总和=4589200.00, 平均=4589.20, 最大=28000.00, 最小=120.00
─ 上架日期 (date)
  范围: 2024-01-01 ~ 2024-12-31
─ 库存数量 (int)
  统计: 总和=152000, 平均=152, 最大=2000, 最小=0
─ 好评率 (percent)
  统计: 总和=92500.00, 平均=92.50, 最大=100.00, 最小=45.00

【样本数据(前5行)】
行1: 菜品ID=1, 菜品名称=宫保鸡丁, 价格=38, 销售额=4560, ...
行2: 菜品ID=2, 菜品名称=麻婆豆腐, 价格=28, 销售额=3360, ...
行3: 菜品ID=3, 菜品名称=红烧肉, 价格=48, 销售额=5760, ...
行4: 菜品ID=4, 菜品名称=清蒸鲈鱼, 价格=88, 销售额=10560, ...
行5: 菜品ID=5, 菜品名称=水煮牛肉, 价格=68, 销售额=8160, ...
```

**移植要点对照表**：

| 前端逻辑 (JavaScript) | 后端实现 (Python) | 对齐说明 |
|----------------------|------------------|---------|
| `Math.round(sum*100)/100` | `round(total, 2)` | 总和/平均值保留 2 位小数 |
| `Math.max.apply(null, vals)` | `max(vals)` | 最大值计算 |
| `Math.min.apply(null, vals)` | `min(vals)` | 最小值计算 |
| `uniqKeys.length <= 20` | `len(uniq_keys) <= 20` | 唯一值 ≤ 20 显示全部 |
| `uniqKeys.slice(0,10)` | `uniq_keys[:10]` | Top 10 取值 |
| `dates.sort()` | `sorted(dates)` | 日期排序取范围 |
| `rows.slice(0, 5)` | `rows[:5]` | 前 5 行样本 |

---

## 5. SQL 执行器 (core/sql_executor.py)

### 5.1 安全校验

SQL 执行器是安全的核心防线。用户问题经过 LLM 生成的 SQL 必须通过安全校验后才能在 SQLite 上执行，防止 SQL 注入和未授权的数据修改。

创建 `core/sql_executor.py`：

```python
"""
core/sql_executor.py — SQL 执行器

负责：
1. SQL 安全校验 — 只允许 SELECT，禁止所有写操作
2. SQL 执行 — 在指定数据集的 SQLite 文件上执行查询
3. 结果格式化 — 返回列名、行数据、行数

安全策略：
- 白名单模式：只允许 SELECT 语句
- 黑名单模式：禁止 INSERT/UPDATE/DELETE/DROP/ALTER/CREATE 等关键词
- 多语句检测：禁止分号（防止 SQL 注入的多语句执行）
- 子查询校验：子查询中同样禁止写操作
- 行数限制：最大返回 10000 行，防止内存溢出
"""

import re
import sqlite3
from typing import Optional

from config import SQL_EXECUTOR_CONFIG


class SQLValidationError(Exception):
    """SQL 校验失败异常。"""

    def __init__(self, message: str, sql: str = ''):
        self.sql = sql
        super().__init__(message)


class SQLExecutor:
    """SQL 执行器：安全校验 + 执行。

    对应前端基于 parsedData.rows 的内存 SQL 执行逻辑，
    但改为在后端 SQLite 数据库引擎上执行，支持 100K+ 行数据。
    """

    def __init__(self):
        self.max_return_rows = SQL_EXECUTOR_CONFIG['max_return_rows']
        self.forbidden_keywords = SQL_EXECUTOR_CONFIG['forbidden_keywords']
        self.forbidden_functions = SQL_EXECUTOR_CONFIG['forbidden_functions']
        self.execution_timeout = SQL_EXECUTOR_CONFIG['execution_timeout']

    # ============================================================
    # 安全校验
    # ============================================================

    def validate(self, sql: str) -> str:
        """校验 SQL 语句的安全性。

        校验规则（按顺序执行，任一失败即拒绝）：
        1. 非空检查
        2. 多语句检测 — 禁止分号（防止多语句注入）
        3. 语句类型检查 — 必须以 SELECT 开头
        4. 禁止关键词检查 — INSERT/UPDATE/DELETE/DROP 等
        5. 禁止函数检查 — LOAD_EXTENSION 等危险函数
        6. 子查询写操作检查 — 子查询中同样禁止写操作

        Args:
            sql: 待校验的 SQL 语句

        Returns:
            清理后的 SQL 语句（去除首尾空白）

        Raises:
            SQLValidationError: 校验失败时抛出，message 包含失败原因
        """
        if not sql or not sql.strip():
            raise SQLValidationError('SQL 语句为空', sql)

        # 清理 SQL：去除首尾空白和注释
        sql_clean = sql.strip().rstrip(';').strip()

        # 1. 多语句检测 — 禁止分号
        # 前端没有此检查（因为前端是内存执行），但后端必须防止 SQL 注入
        if ';' in sql_clean:
            raise SQLValidationError(
                '禁止多语句执行（检测到分号）', sql
            )

        # 2. 语句类型检查 — 必须以 SELECT 开头
        # 使用大小写不敏感匹配
        if not re.match(r'^\s*SELECT\b', sql_clean, re.IGNORECASE):
            raise SQLValidationError(
                '只允许 SELECT 查询语句', sql
            )

        # 3. 禁止关键词检查
        # 使用正则匹配完整单词，避免误匹配（如字段名包含 "update_time"）
        for keyword in self.forbidden_keywords:
            # \b 确保匹配的是完整单词，而非字段名的一部分
            pattern = rf'\b{keyword}\b'
            if re.search(pattern, sql_clean, re.IGNORECASE):
                raise SQLValidationError(
                    f'SQL 中包含禁止的关键词: {keyword}', sql
                )

        # 4. 禁止函数检查
        for func in self.forbidden_functions:
            pattern = rf'\b{func}\s*\('
            if re.search(pattern, sql_clean, re.IGNORECASE):
                raise SQLValidationError(
                    f'SQL 中包含禁止的函数: {func}', sql
                )

        # 5. 注释检测 — 禁止 SQL 注释（防止通过注释绕过校验）
        if '--' in sql_clean or '/*' in sql_clean or '*/' in sql_clean:
            raise SQLValidationError(
                'SQL 中不允许包含注释', sql
            )

        return sql_clean
```

### 5.2 SQL 执行

以下代码继续在 `core/sql_executor.py` 中（接上面的 `SQLExecutor.validate` 方法之后），包含 `execute` 和 `execute_raw` 方法：

```python
    # ============================================================
    # SQL 执行
    # ============================================================

    def execute(self, sql: str, db_path: str) -> dict:
        """在指定 SQLite 数据库上执行 SQL 查询。

        执行流程：
        1. 调用 validate() 校验 SQL 安全性
        2. 连接 SQLite 数据库
        3. 设置执行超时
        4. 执行查询
        5. 限制返回行数
        6. 格式化结果返回

        Args:
            sql: SQL 查询语句
            db_path: SQLite 数据库文件路径

        Returns:
            dict: {
                'columns': list[str],   # 列名列表
                'rows': list[dict],     # 查询结果，每行是 {列名: 值} 字典
                'count': int            # 返回行数
            }

        Raises:
            SQLValidationError: SQL 安全校验失败
            Exception: SQL 执行错误（语法错误、表不存在等）
        """
        # 1. 安全校验
        sql_clean = self.validate(sql)

        # 2. 连接数据库并执行
        conn = sqlite3.connect(db_path)
        try:
            # 设置执行超时（秒）
            conn.set_progress_handler(
                lambda: None,
                100000  # 每 100000 个虚拟机指令检查一次
            )

            cursor = conn.cursor()

            # 执行查询
            cursor.execute(sql_clean)

            # 获取列名
            columns = [desc[0] for desc in cursor.description] if cursor.description else []

            # 获取结果，限制最大行数
            rows = cursor.fetchmany(self.max_return_rows)
            row_count = len(rows)

            # 转换为字典列表
            result_rows = [dict(zip(columns, row)) for row in rows]

            return {
                'columns': columns,
                'rows': result_rows,
                'count': row_count,
            }
        except sqlite3.Error as e:
            # SQL 执行错误（语法错误、表不存在、列不存在等）
            raise Exception(f'SQL 执行失败: {str(e)}') from e
        finally:
            conn.close()

    def execute_raw(self, sql: str, db_path: str) -> tuple:
        """执行 SQL 并返回原始结果（不转为字典，性能更高）。

        用于需要高性能的场景（如大批量数据处理）。

        Returns:
            tuple: (columns: list[str], rows: list[tuple], count: int)
        """
        sql_clean = self.validate(sql)

        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(sql_clean)
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            rows = cursor.fetchmany(self.max_return_rows)
            return columns, rows, len(rows)
        finally:
            conn.close()


# ============================================================
# 模块级单例
# ============================================================

sql_executor = SQLExecutor()
```

---

## 6. API 路由 (routes/)

### 6.1 上传路由 (routes/upload.py)

创建 `routes/upload.py`：

```python
"""
routes/upload.py — 文件上传路由

处理用户上传的 CSV / Excel 文件，解析后返回数据集元信息。

对应前端 parseCSVFile(file) [行 2823] 的后端 API 实现。
"""

import time
from flask import Blueprint, request, jsonify
from werkzeug.utils import secure_filename

from core.data_manager import data_manager
from config import UPLOAD_CONFIG

bp = Blueprint('upload', __name__)


@bp.route('/api/upload', methods=['POST'])
def upload():
    """文件上传接口。

    请求格式: multipart/form-data
    请求参数:
        file: 上传的文件（CSV / XLSX / XLS）

    响应格式:
        成功 (200):
            {
                "success": true,
                "data": {
                    "dataset_id": "ds-1234567890-abcdef12",
                    "original_name": "restaurant_menu_test.csv",
                    "file_size": 102400,
                    "row_count": 1000,
                    "columns": ["菜品ID", "菜品名称", "价格", ...],
                    "field_info": [
                        {"name": "菜品ID", "type": "text", "nullRate": "0%", "sample": "1"},
                        {"name": "价格", "type": "currency", "nullRate": "0%", "sample": "38"},
                        ...
                    ]
                }
            }
        失败 (400):
            {
                "success": false,
                "error": "错误描述"
            }
    """
    # 1. 检查是否有文件
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': '未上传文件'}), 400

    file = request.files['file']
    if not file or not file.filename:
        return jsonify({'success': False, 'error': '文件名为空'}), 400

    # 2. 检查文件大小（Content-Length 头）
    max_size = UPLOAD_CONFIG['max_file_size_mb'] * 1024 * 1024
    if request.content_length and request.content_length > max_size:
        return jsonify({
            'success': False,
            'error': f'文件大小超过限制 {UPLOAD_CONFIG["max_file_size_mb"]}MB'
        }), 400

    # 3. 调用 DataManager 处理上传
    start_time = time.time()
    try:
        result = data_manager.upload_file(file)
        elapsed_ms = int((time.time() - start_time) * 1000)

        return jsonify({
            'success': True,
            'data': result,
            'response_time_ms': elapsed_ms,
        }), 200

    except ValueError as e:
        # 文件校验失败（格式不支持、大小超限等）
        return jsonify({'success': False, 'error': str(e)}), 400

    except Exception as e:
        # 解析或存储失败
        return jsonify({
            'success': False,
            'error': f'文件解析失败: {str(e)}'
        }), 500
```

### 6.2 Schema 路由 (routes/schema.py)

创建 `routes/schema.py`：

```python
"""
routes/schema.py — 数据 Schema 查询路由

返回指定数据集的字段信息和样例数据，供前端构建数据画像和字段列表。

对应前端 parsedData.fieldInfo + parsedData.rows[:5] 的数据。
"""

from flask import Blueprint, jsonify

from core.data_manager import data_manager

bp = Blueprint('schema', __name__)


@bp.route('/api/schema/<dataset_id>', methods=['GET'])
def get_schema(dataset_id: str):
    """获取数据集的 Schema 信息。

    路径参数:
        dataset_id: 数据集ID

    响应格式:
        成功 (200):
            {
                "success": true,
                "data": {
                    "dataset_id": "ds-1234567890-abcdef12",
                    "original_name": "restaurant_menu_test.csv",
                    "row_count": 1000,
                    "columns": ["菜品ID", "菜品名称", "价格", ...],
                    "field_info": [
                        {"name": "菜品ID", "type": "text", "nullRate": "0%", "sample": "1"},
                        ...
                    ],
                    "sample_rows": [
                        {"菜品ID": 1, "菜品名称": "宫保鸡丁", "价格": 38, ...},
                        ...
                    ]
                }
            }
        失败 (404):
            {
                "success": false,
                "error": "数据集不存在"
            }
    """
    try:
        schema = data_manager.get_schema(dataset_id)
        return jsonify({'success': True, 'data': schema}), 200

    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 404

    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'获取 Schema 失败: {str(e)}'
        }), 500


@bp.route('/api/profile/<dataset_id>', methods=['GET'])
def get_data_profile(dataset_id: str):
    """获取数据集的数据画像文本。

    返回前端 buildDataProfile() [行 4347] 的等价文本，
    可直接用作 LLM 的数据上下文。

    路径参数:
        dataset_id: 数据集ID

    响应格式:
        成功 (200):
            {
                "success": true,
                "data": {
                    "dataset_id": "ds-...",
                    "profile": "【数据概况】\n文件名: ...\n..."
                }
            }
    """
    try:
        profile = data_manager.build_data_profile(dataset_id)
        return jsonify({
            'success': True,
            'data': {
                'dataset_id': dataset_id,
                'profile': profile,
            }
        }), 200

    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 404

    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'构建数据画像失败: {str(e)}'
        }), 500
```

### 6.3 历史路由 (routes/history.py)

创建 `routes/history.py`：

```python
"""
routes/history.py — 查询历史路由

返回指定数据集的查询历史记录列表。

对应前端 conversations 数组中每个对话的 messages 历史。
"""

from flask import Blueprint, request, jsonify

from models import get_session
from models.query_history import QueryHistory

bp = Blueprint('history', __name__)


@bp.route('/api/history/<dataset_id>', methods=['GET'])
def get_history(dataset_id: str):
    """获取指定数据集的查询历史。

    路径参数:
        dataset_id: 数据集ID

    查询参数:
        limit: 返回条数上限（默认 50）
        offset: 偏移量（默认 0），用于分页

    响应格式:
        成功 (200):
            {
                "success": true,
                "data": {
                    "dataset_id": "ds-...",
                    "total": 30,
                    "history": [
                        {
                            "id": 1,
                            "dataset_id": "ds-...",
                            "question": "各部门的平均薪资是多少",
                            "sql_text": "SELECT 部门, AVG(薪资) AS 平均薪资 FROM ...",
                            "result": {"columns": [...], "rows": [...], "count": 5},
                            "chart_config": {"chartType": "bar", ...},
                            "insight": "技术部平均薪资最高...",
                            "cached": false,
                            "response_time_ms": 2300,
                            "created_at": "2025-01-15T10:30:00"
                        },
                        ...
                    ]
                }
            }
        失败 (404):
            {
                "success": false,
                "error": "数据集不存在"
            }
    """
    # 解析分页参数
    limit = min(int(request.args.get('limit', 50)), 200)  # 最大 200 条
    offset = int(request.args.get('offset', 0))

    session = get_session()
    try:
        # 查询历史记录，按时间倒序
        query = session.query(QueryHistory).filter_by(dataset_id=dataset_id)

        # 获取总数
        total = query.count()

        # 分页查询
        records = (
            query
            .order_by(QueryHistory.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

        history = [record.to_dict() for record in records]

        return jsonify({
            'success': True,
            'data': {
                'dataset_id': dataset_id,
                'total': total,
                'history': history,
            }
        }), 200

    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'获取查询历史失败: {str(e)}'
        }), 500

    finally:
        session.close()


@bp.route('/api/history/<dataset_id>/<int:history_id>', methods=['GET'])
def get_history_detail(dataset_id: str, history_id: int):
    """获取单条查询历史详情。

    路径参数:
        dataset_id: 数据集ID
        history_id: 历史记录ID
    """
    session = get_session()
    try:
        record = session.query(QueryHistory).filter_by(
            id=history_id,
            dataset_id=dataset_id
        ).first()

        if not record:
            return jsonify({'success': False, 'error': '历史记录不存在'}), 404

        return jsonify({'success': True, 'data': record.to_dict()}), 200

    finally:
        session.close()
```

### 6.4 删除路由 (routes/dataset.py)

创建 `routes/dataset.py`：

```python
"""
routes/dataset.py — 数据集删除路由

删除数据集及其所有关联数据（查询历史、缓存条目、SQLite 文件、上传文件）。
"""

from flask import Blueprint, jsonify

from core.data_manager import data_manager

bp = Blueprint('dataset', __name__)


@bp.route('/api/dataset/<dataset_id>', methods=['DELETE'])
def delete_dataset(dataset_id: str):
    """删除数据集及所有关联数据。

    删除范围：
    1. metadata.db 中的 Dataset 记录
    2. metadata.db 中的 QueryHistory 记录
    3. metadata.db 中的 CacheEntry 记录
    4. 独立的 SQLite 数据库文件
    5. 上传的原始文件

    路径参数:
        dataset_id: 数据集ID

    响应格式:
        成功 (200):
            {
                "success": true,
                "message": "数据集已删除",
                "dataset_id": "ds-..."
            }
        失败 (404):
            {
                "success": false,
                "error": "数据集不存在"
            }
    """
    try:
        data_manager.delete_dataset(dataset_id)
        return jsonify({
            'success': True,
            'message': '数据集已删除',
            'dataset_id': dataset_id,
        }), 200

    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 404

    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'删除数据集失败: {str(e)}'
        }), 500
```

---

## 7. Flask 主应用 (app.py)

创建项目根目录下的 `app.py`，采用应用工厂模式：

```python
"""
app.py — Flask 主应用入口

采用应用工厂模式（Application Factory Pattern），
便于测试和扩展（如创建不同配置的实例）。

功能：
- 应用工厂 create_app()
- 蓝图注册（upload / schema / history / dataset）
- CORS 跨域配置
- 全局错误处理
- 健康检查端点
- 数据库初始化
"""

import logging
from logging.handlers import RotatingFileHandler

from flask import Flask, jsonify
from flask_cors import CORS

from config import FLASK_CONFIG, get_config_summary, LOG_DIR


def create_app(config_name: str = 'default') -> Flask:
    """Flask 应用工厂。

    Args:
        config_name: 配置名称（预留，当前未使用不同配置）

    Returns:
        配置完成的 Flask 应用实例
    """
    app = Flask(__name__)

    # ============================================================
    # 1. 加载配置
    # ============================================================
    app.config['SECRET_KEY'] = FLASK_CONFIG['secret_key']
    app.config['JSON_AS_ASCII'] = FLASK_CONFIG['json_as_ascii']  # 中文直接输出
    app.config['DEBUG'] = FLASK_CONFIG['debug']
    app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 最大请求体 50MB

    # ============================================================
    # 2. 配置 CORS（跨域）
    # ============================================================
    CORS(app, resources={
        r'/api/*': {
            'origins': '*',                    # 允许所有来源（开发环境）
            'methods': ['GET', 'POST', 'DELETE', 'OPTIONS'],
            'allow_headers': ['Content-Type', 'Authorization'],
        }
    })

    # ============================================================
    # 3. 配置日志
    # ============================================================
    _setup_logging(app)

    # ============================================================
    # 4. 初始化数据库
    # ============================================================
    from models import init_db
    init_db()

    # ============================================================
    # 5. 注册蓝图
    # ============================================================
    from routes.upload import bp as upload_bp
    from routes.schema import bp as schema_bp
    from routes.history import bp as history_bp
    from routes.dataset import bp as dataset_bp

    app.register_blueprint(upload_bp)
    app.register_blueprint(schema_bp)
    app.register_blueprint(history_bp)
    app.register_blueprint(dataset_bp)

    # ============================================================
    # 6. 健康检查端点
    # ============================================================
    @app.route('/api/health', methods=['GET'])
    def health_check():
        """健康检查端点。

        返回服务状态和配置摘要（敏感信息已隐藏）。
        用于负载均衡器健康检查和运维监控。
        """
        return jsonify({
            'status': 'ok',
            'service': 'shufen-backend',
            'version': '1.0.0',
            'config': get_config_summary(),
        }), 200

    # ============================================================
    # 7. 根路径 — API 信息
    # ============================================================
    @app.route('/', methods=['GET'])
    def api_info():
        """根路径，返回 API 信息。"""
        return jsonify({
            'service': '数分精灵后端 API',
            'version': '1.0.0',
            'endpoints': {
                'health': 'GET /api/health',
                'upload': 'POST /api/upload',
                'schema': 'GET /api/schema/<dataset_id>',
                'profile': 'GET /api/profile/<dataset_id>',
                'history': 'GET /api/history/<dataset_id>',
                'history_detail': 'GET /api/history/<dataset_id>/<history_id>',
                'delete': 'DELETE /api/dataset/<dataset_id>',
            }
        }), 200

    # ============================================================
    # 8. 全局错误处理
    # ============================================================
    @app.errorhandler(400)
    def bad_request(error):
        return jsonify({'success': False, 'error': '请求参数错误'}), 400

    @app.errorhandler(404)
    def not_found(error):
        return jsonify({'success': False, 'error': '资源不存在'}), 404

    @app.errorhandler(413)
    def request_entity_too_large(error):
        return jsonify({'success': False, 'error': '请求体过大，最大 50MB'}), 413

    @app.errorhandler(500)
    def internal_server_error(error):
        app.logger.error(f'内部服务器错误: {error}')
        return jsonify({'success': False, 'error': '内部服务器错误'}), 500

    # ============================================================
    # 9. 启动日志
    # ============================================================
    app.logger.info('=' * 60)
    app.logger.info('数分精灵后端启动')
    app.logger.info(f'配置摘要: {get_config_summary()}')
    app.logger.info('=' * 60)

    return app


def _setup_logging(app: Flask):
    """配置应用日志。"""
    log_file = LOG_DIR / 'app.log'

    # 设置日志格式
    formatter = logging.Formatter(
        '[%(asctime)s] %(levelname)s in %(module)s: %(message)s'
    )

    # 文件日志（轮转，最大 10MB，保留 5 个备份）
    file_handler = RotatingFileHandler(
        str(log_file),
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)

    # 控制台日志
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.DEBUG if FLASK_CONFIG['debug'] else logging.INFO)

    # 应用到 Flask logger
    app.logger.handlers.clear()
    app.logger.addHandler(file_handler)
    app.logger.addHandler(console_handler)
    app.logger.setLevel(logging.DEBUG if FLASK_CONFIG['debug'] else logging.INFO)


# ============================================================
# 应用入口
# ============================================================

app = create_app()


if __name__ == '__main__':
    app.run(
        host=FLASK_CONFIG['host'],
        port=FLASK_CONFIG['port'],
        debug=FLASK_CONFIG['debug'],
    )
```

---

## 8. 启动和测试

### 8.1 启动命令

#### 开发环境

```bash
# 激活虚拟环境后，在项目根目录执行
python app.py
```

或使用 Flask CLI：

```bash
# 设置 FLASK_APP 环境变量（Windows PowerShell）
$env:FLASK_APP = "app.py"
$env:FLASK_ENV = "development"
flask run --host 0.0.0.0 --port 5000
```

```bash
# Linux / macOS
export FLASK_APP=app.py
export FLASK_ENV=development
flask run --host 0.0.0.0 --port 5000
```

启动成功后，终端输出：

```
[DB] 数据库已初始化: sqlite:///.../data/metadata.db
============================================================
[INFO] 数分精灵后端启动
[INFO] 配置摘要: {'llm_model': 'deepseek-chat', ...}
============================================================
 * Running on http://0.0.0.0:5000
```

#### 生产环境（Gunicorn）

```bash
# Linux / macOS（Windows 上使用 waitress 或 Docker 部署）
gunicorn \
    --bind 0.0.0.0:5000 \
    --workers 4 \
    --threads 2 \
    --timeout 120 \
    --access-logfile logs/access.log \
    --error-logfile logs/error.log \
    "app:app"
```

参数说明：

| 参数 | 值 | 说明 |
|------|------|------|
| `--workers` | 4 | 工作进程数（建议 CPU 核数 * 2 + 1） |
| `--threads` | 2 | 每个进程的线程数 |
| `--timeout` | 120 | 请求超时（秒），需要覆盖 LLM 调用的长耗时 |
| `--access-logfile` | logs/access.log | 访问日志文件 |
| `--error-logfile` | logs/error.log | 错误日志文件 |

### 8.2 测试用例

使用 `curl` 测试每个 API 接口。

#### 8.2.1 健康检查

```bash
curl http://localhost:5000/api/health
```

预期响应：

```json
{
  "status": "ok",
  "service": "shufen-backend",
  "version": "1.0.0",
  "config": {
    "llm_model": "deepseek-chat",
    "llm_base_url": "https://api.deepseek.com",
    "llm_api_key_set": true,
    "metadata_db_path": "...\\data\\metadata.db",
    "faiss_threshold": 0.92,
    "faiss_max_entries": 10000,
    "embedding_model": "paraphrase-multilingual-MiniLM-L12-v2",
    "max_file_size_mb": 50,
    "allowed_extensions": ["csv", "xlsx", "xls"],
    "debug_mode": true
  }
}
```

#### 8.2.2 上传文件

```bash
# 上传 CSV 文件
curl -X POST http://localhost:5000/api/upload \
  -F "file=@restaurant_menu_test.csv"

# 上传 Excel 文件
curl -X POST http://localhost:5000/api/upload \
  -F "file=@data.xlsx"
```

预期响应：

```json
{
  "success": true,
  "data": {
    "dataset_id": "ds-1737500000-a1b2c3d4",
    "original_name": "restaurant_menu_test.csv",
    "file_size": 51200,
    "row_count": 1000,
    "columns": ["菜品ID", "菜品名称", "分类", "价格", "销售额", "上架日期", "库存数量", "好评率"],
    "field_info": [
      {"name": "菜品ID", "type": "text", "nullRate": "0.0%", "sample": "1"},
      {"name": "菜品名称", "type": "text", "nullRate": "0.0%", "sample": "宫保鸡丁"},
      {"name": "分类", "type": "text", "nullRate": "0.0%", "sample": "川菜"},
      {"name": "价格", "type": "currency", "nullRate": "0.0%", "sample": "38"},
      {"name": "销售额", "type": "currency", "nullRate": "0.0%", "sample": "4560"},
      {"name": "上架日期", "type": "date", "nullRate": "0.0%", "sample": "2024-01-01"},
      {"name": "库存数量", "type": "int", "nullRate": "0.0%", "sample": "200"},
      {"name": "好评率", "type": "percent", "nullRate": "0.0%", "sample": "95.5"}
    ]
  },
  "response_time_ms": 850
}
```

> 保存返回的 `dataset_id`，后续测试需要使用。

#### 8.2.3 获取 Schema

```bash
# 替换 <dataset_id> 为上传时返回的 ID
curl http://localhost:5000/api/schema/ds-1737500000-a1b2c3d4
```

预期响应：

```json
{
  "success": true,
  "data": {
    "dataset_id": "ds-1737500000-a1b2c3d4",
    "original_name": "restaurant_menu_test.csv",
    "row_count": 1000,
    "columns": ["菜品ID", "菜品名称", "分类", "价格", "销售额", "上架日期", "库存数量", "好评率"],
    "field_info": [...],
    "sample_rows": [
      {"菜品ID": 1, "菜品名称": "宫保鸡丁", "分类": "川菜", "价格": 38, ...},
      {"菜品ID": 2, "菜品名称": "麻婆豆腐", "分类": "川菜", "价格": 28, ...},
      {"菜品ID": 3, "菜品名称": "红烧肉", "分类": "鲁菜", "价格": 48, ...},
      {"菜品ID": 4, "菜品名称": "清蒸鲈鱼", "分类": "粤菜", "价格": 88, ...},
      {"菜品ID": 5, "菜品名称": "水煮牛肉", "分类": "川菜", "价格": 68, ...}
    ]
  }
}
```

#### 8.2.4 获取数据画像

```bash
curl http://localhost:5000/api/profile/ds-1737500000-a1b2c3d4
```

预期响应：

```json
{
  "success": true,
  "data": {
    "dataset_id": "ds-1737500000-a1b2c3d4",
    "profile": "【数据概况】\n文件名: restaurant_menu_test.csv\n总行数: 1000\n字段数: 8\n\n【字段详情】\n─ 菜品ID (text)\n  取值(1000个), Top10: 1(1), 2(1), 3(1), ...\n─ 菜品名称 (text)\n  取值(150个), Top10: 宫保鸡丁(12), ...\n─ 价格 (currency)\n  统计: 总和=125800.5, 平均=125.8, 最大=580.0, 最小=15.0\n─ 上架日期 (date)\n  范围: 2024-01-01 ~ 2024-12-31\n─ 库存数量 (int)\n  统计: 总和=152000, 平均=152.0, 最大=2000, 最小=0\n─ 好评率 (percent)\n  统计: 总和=92500.0, 平均=92.5, 最大=100.0, 最小=45.0\n\n【样本数据(前5行)】\n行1: 菜品ID=1, 菜品名称=宫保鸡丁, ...\n..."
  }
}
```

#### 8.2.5 获取查询历史

```bash
# 获取最近 50 条历史
curl "http://localhost:5000/api/history/ds-1737500000-a1b2c3d4?limit=50"

# 分页查询（第 2 页，每页 10 条）
curl "http://localhost:5000/api/history/ds-1737500000-a1b2c3d4?limit=10&offset=10"
```

预期响应：

```json
{
  "success": true,
  "data": {
    "dataset_id": "ds-1737500000-a1b2c3d4",
    "total": 0,
    "history": []
  }
}
```

> 查询历史在后续模块（LLM 查询接口）实现后才会有数据。

#### 8.2.6 删除数据集

```bash
curl -X DELETE http://localhost:5000/api/dataset/ds-1737500000-a1b2c3d4
```

预期响应：

```json
{
  "success": true,
  "message": "数据集已删除",
  "dataset_id": "ds-1737500000-a1b2c3d4"
}
```

#### 8.2.7 测试错误场景

```bash
# 上传不支持的文件格式
curl -X POST http://localhost:5000/api/upload \
  -F "file=@test.txt"

# 预期响应：{"success": false, "error": "不支持的文件格式: .txt..."}

# 查询不存在的数据集
curl http://localhost:5000/api/schema/ds-not-exist

# 预期响应：{"success": false, "error": "数据集不存在: ds-not-exist"}

# 删除不存在的数据集
curl -X DELETE http://localhost:5000/api/dataset/ds-not-exist

# 预期响应：{"success": false, "error": "数据集不存在: ds-not-exist"}
```

### 8.3 常见问题排查

#### 问题 1：`ModuleNotFoundError: No module named 'config'`

**原因**：Python 路径未包含项目根目录。

**解决**：

```bash
# 方法 1：在项目根目录运行（推荐）
cd "e:\数分精灵demo minmax\最新版-数分ai"
python app.py

# 方法 2：设置 PYTHONPATH（Windows PowerShell）
$env:PYTHONPATH = "."

# 方法 3：设置 PYTHONPATH（Linux / macOS）
export PYTHONPATH=$(pwd)
```

#### 问题 2：`faiss-cpu` 安装失败（Windows）

**原因**：Windows 上 `faiss-cpu` 的 pip 包可能不兼容。

**解决**：

```bash
# 方法 1：使用 conda 安装
conda install -c conda-forge faiss-cpu

# 方法 2：安装预编译版本
pip install faiss-cpu --no-build-isolation

# 方法 3：如果仅需本模块功能（暂不使用 FAISS），可以先注释掉 faiss 相关依赖
# 在 config.py 中注释掉 FAISS_CONFIG 相关部分
# 在 requirements.txt 中注释掉 faiss-cpu 和 sentence-transformers
```

#### 问题 3：`sentence-transformers` 模型下载缓慢

**原因**：首次使用时，`paraphrase-multilingual-MiniLM-L12-v2` 模型需要从 HuggingFace 下载（约 120MB）。

**解决**：

```bash
# 方法 1：设置 HuggingFace 镜像（国内推荐）
# Windows PowerShell
$env:HF_ENDPOINT = "https://hf-mirror.com"

# Linux / macOS
export HF_ENDPOINT=https://hf-mirror.com

# 方法 2：手动下载模型到本地缓存目录
# 模型下载后存放在 ~/.cache/huggingface/ 或 C:\Users\<用户名>\.cache\huggingface\

# 方法 3：使用国内模型源
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple sentence-transformers
```

#### 问题 4：Excel 文件解析失败

**原因**：缺少 `openpyxl` 或 `xlrd` 引擎。

**解决**：

```bash
# 安装 Excel 解析引擎
pip install openpyxl xlrd

# .xlsx 文件需要 openpyxl
# .xls 文件需要 xlrd（注意 xlrd 2.0+ 不再支持 .xls，需安装 1.2 版本）
pip install xlrd==1.2.0
```

#### 问题 5：CORS 跨域错误

**原因**：前端和后端运行在不同端口。

**解决**：`app.py` 中已配置 `CORS(app, resources={r'/api/*': {'origins': '*'}})`，允许所有来源跨域访问。如果仍然遇到 CORS 错误：

```bash
# 检查 Flask-CORS 是否正确安装
pip show flask-cors

# 确保前端请求的 URL 正确
# 前端：http://localhost:8080/index.html
# 后端：http://localhost:5000/api/...
# 前端请求应指向 http://localhost:5000/api/...
```

#### 问题 6：数据库锁定（`database is locked`）

**原因**：SQLite 并发写入冲突。

**解决**：

```python
# 在 config.py 的 DATABASE_CONFIG 中调整连接池配置
'sqlalchemy_engine_options': {
    'pool_pre_ping': True,
    'pool_recycle': 3600,
    'pool_size': 5,          # 减小连接池
    'max_overflow': 10,       # 减小溢出
    'connect_args': {
        'timeout': 30,        # 增加等待超时
        'check_same_thread': False,  # 允许跨线程
    },
}
```

#### 问题 7：上传文件大小限制

**原因**：Flask 默认和 `config.py` 中的大小限制。

**解决**：

```python
# 在 app.py 中调整 MAX_CONTENT_LENGTH
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB

# 同时在 .env 中调整
# MAX_FILE_SIZE_MB=100
```

#### 问题 8：中文文件名乱码

**原因**：Windows 系统默认编码非 UTF-8。

**解决**：

```python
# 在 app.py 开头添加（如果仍有问题）
import sys
sys.stdout.reconfigure(encoding='utf-8')

# 或在 config.py 中设置环境变量
import os
os.environ['PYTHONIOENCODING'] = 'utf-8'
```

---

## 附录：前后端逻辑对照表

| 前端函数 | 行号 | 后端对应模块 | 后端文件 | 移植状态 |
|---------|------|------------|---------|---------|
| `parseCSVFile(file)` | 2823 | `DataManager.upload_file()` | `core/data_manager.py` | 完整移植 |
| `setParsedData(...)` | 2941 | `DataManager.upload_file()` 内部 | `core/data_manager.py` | 完整移植 |
| `inferFieldInfo(columns, rows)` | 2950 | `infer_field_info()` | `core/data_manager.py` | 完整移植 |
| `inferFieldType(name, values)` | 2963 | `infer_field_type()` | `core/data_manager.py` | 完整移植 |
| `buildDataProfile()` | 4347 | `DataManager.build_data_profile()` | `core/data_manager.py` | 完整移植 |
| `computeTypeDistribution()` | 2987 | 前端保留 | - | 无需移植 |
| 前端内存 SQL 执行 | - | `SQLExecutor.execute()` | `core/sql_executor.py` | 重新实现 |
| 前端 ECharts 渲染 | 12143 | 前端保留 | - | 无需移植 |
| 前端 LLM 调用 | 4256 | 后续模块实现 | `core/llm_client.py` | 待实现 |
| 前端意图分类 | 4642 | 后续模块实现 | `core/intent_classifier.py` | 待实现 |
| 前端 SQL 生成 | 8674 | 后续模块实现 | `core/sql_generator.py` | 待实现 |

---

*本文档为"数分精灵"改造方案的第二个模块，后续模块将基于本文档搭建的后端框架，实现 LLM 引擎、FAISS 语义缓存和自动洞察等高级功能。*
