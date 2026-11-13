"""测试套件统一环境隔离与生命周期管理工具。

确保每个测试文件既能独立作为脚本运行（python file.py），也能在 pytest
跨文件级联多模块执行时 100% 独立稳定执行，避免单例连接挂起或数据目录丢失。
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

# 确保 kruskal 的 backend 目录排在 sys.path 首位，防止全局 editable 安装的同名 app 包造成命名空间污染
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))
_ROOT_DIR = _BACKEND_DIR.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

# 确保在导入任何应用模块前优先设置隔离的测试数据环境，防止模块导入阶段副作用污染真实数据
_preimport_tmp = tempfile.mkdtemp(prefix="kruskal_test_isolation_")
os.environ.setdefault("KRUSKAL_DATA_DIR", _preimport_tmp)
os.environ.setdefault("KRUSKAL_DEV", "1")
os.environ.setdefault("KRUSKAL_CSP", "0")

from starlette.testclient import TestClient

from app import auth as authz
from app import config, crypto, db, vault
from app.db import init_db
from app.main import app


class TestEnvironment:
    """每个测试套件独立的沙箱环境实例。"""
    __test__ = False

    def __init__(self, prefix: str = "kruskal_test_"):
        self.tmp_dir = tempfile.mkdtemp(prefix=prefix, dir=tempfile.gettempdir())
        self.data_dir = Path(self.tmp_dir) / "data"
        self.client = TestClient(app)
        self.token: str = ""

    def setup(self) -> None:
        """初始化测试数据库、本机用户、数据密钥与会话 token。"""
        os.environ["KRUSKAL_DATA_DIR"] = str(self.data_dir)
        os.environ["KRUSKAL_DEV"] = "1"
        os.environ["KRUSKAL_CSP"] = "0"

        db.close_conn()
        vault.clear_dek()
        config.rebind_data_dir(self.data_dir)
        init_db()
        user = authz.ensure_local_user()
        vault.set_dek(crypto.new_dek())
        self.token = authz.issue_token(user["id"])
        assert vault.has_dek(), "测试环境初始化后 DEK 应已就绪"

    def auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def teardown(self) -> None:
        """清理连接、DEK 与临时数据目录。"""
        db.close_conn()
        vault.clear_dek()
        try:
            shutil.rmtree(self.tmp_dir, ignore_errors=True)
        except Exception:
            pass
