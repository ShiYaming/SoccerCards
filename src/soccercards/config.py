"""配置加载：环境变量 + 可选 .env 文件（不引入第三方依赖）。"""

from __future__ import annotations

import os
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


class Config:
    def __init__(self) -> None:
        project_root = Path(__file__).resolve().parent.parent.parent
        _load_dotenv(project_root / ".env")
        _load_dotenv(Path(os.getcwd()) / ".env")

        self.db_path = Path(
            os.environ.get("DB_PATH", str(project_root / "data" / "soccercards.db"))
        )
        self.ebay_client_id = os.environ.get("EBAY_CLIENT_ID", "")
        self.ebay_client_secret = os.environ.get("EBAY_CLIENT_SECRET", "")
        self.ebay_ru_name = os.environ.get("EBAY_RU_NAME", "")
        self.tm_user_agent = os.environ.get(
            "TM_USER_AGENT",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
        )
        try:
            self.request_delay = float(os.environ.get("REQUEST_DELAY_SECONDS", "1.0"))
        except ValueError:
            self.request_delay = 1.0

    @property
    def ebay_configured(self) -> bool:
        return bool(self.ebay_client_id and self.ebay_client_secret)


config = Config()
