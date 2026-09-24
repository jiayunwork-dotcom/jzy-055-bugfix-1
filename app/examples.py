"""随服务发布的两个手算可核对算例。

JSON 文件存放在本模块同级的 examples/ 目录下，接口与测试共用这一份，
避免两处拷贝互相漂移。
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_EXAMPLES_DIR = Path(__file__).resolve().parent / "examples"


@lru_cache(maxsize=1)
def load_examples() -> dict[str, dict]:
    return {
        p.stem: json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(_EXAMPLES_DIR.glob("*.json"))
    }
