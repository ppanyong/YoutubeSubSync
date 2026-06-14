"""后端配置管理：读写 backend/.env，并热更新进程内环境变量。

- 可编辑的配置项见 CONFIG_KEYS。
- 敏感字段（API Key）对外仅返回是否已设置与末 4 位。
- 保存时保留 .env 中的其它键与注释，不存在则基于 .env.example 创建。
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Dict, Optional

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
ENV_EXAMPLE_PATH = BASE_DIR / ".env.example"

# 可在设置页编辑的键。
CONFIG_KEYS = [
    "LLM_BASE_URL",
    "LLM_API_KEY",
    "LLM_MODEL",
    "TARGET_LANG",
]

# 敏感字段：对外脱敏，保存时若提交为空则保留原值。
SENSITIVE_KEYS = {"LLM_API_KEY"}


def _ensure_env_file() -> None:
    """确保 .env 存在；不存在则从 .env.example 复制，再退化为空文件。"""
    if ENV_PATH.exists():
        return
    if ENV_EXAMPLE_PATH.exists():
        shutil.copyfile(ENV_EXAMPLE_PATH, ENV_PATH)
    else:
        ENV_PATH.write_text("", encoding="utf-8")


def _parse_env_text(text: str) -> Dict[str, str]:
    """解析 .env 文本为 key->value，忽略注释与空行。"""
    result: Dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        result[key.strip()] = value.strip()
    return result


def read_env() -> Dict[str, str]:
    """读取 .env 中的全部键值（不含注释）。"""
    if not ENV_PATH.exists():
        return {}
    return _parse_env_text(ENV_PATH.read_text(encoding="utf-8"))


def _mask(value: str) -> str:
    """脱敏：仅保留末 4 位。"""
    if not value:
        return ""
    if len(value) <= 4:
        return "****"
    return "****" + value[-4:]


def get_config_masked() -> Dict[str, object]:
    """返回当前配置（合并 env 与已加载值），敏感字段脱敏。"""
    env = read_env()

    def cur(key: str, default: str = "") -> str:
        # 以进程内环境变量为准（热更新后即时反映），回退到 .env。
        return os.getenv(key, env.get(key, default))

    return {
        "LLM_BASE_URL": cur("LLM_BASE_URL", "https://api.openai.com/v1"),
        "LLM_MODEL": cur("LLM_MODEL", "gpt-4o-mini"),
        "TARGET_LANG": cur("TARGET_LANG", "zh"),
        # 敏感字段：只暴露是否已设置与末 4 位。
        "LLM_API_KEY_SET": bool(cur("LLM_API_KEY")),
        "LLM_API_KEY_MASKED": _mask(cur("LLM_API_KEY")),
    }


def _write_env(updates: Dict[str, str]) -> None:
    """把 updates 写回 .env：更新已存在的键行，追加新键，保留其它内容与注释。"""
    _ensure_env_file()
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    remaining = dict(updates)

    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in remaining:
                new_lines.append(f"{key}={remaining.pop(key)}")
                continue
        new_lines.append(line)

    # 追加 .env 中尚不存在的新键。
    for key, value in remaining.items():
        new_lines.append(f"{key}={value}")

    ENV_PATH.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def save_config(payload: Dict[str, Optional[str]]) -> Dict[str, object]:
    """保存配置：写回 .env 并热更新 os.environ，立即生效。

    规则：敏感字段提交为空（None/空串）时保留原值；其余字段按提交值更新。
    """
    current = read_env()
    updates: Dict[str, str] = {}

    for key in CONFIG_KEYS:
        if key not in payload:
            continue
        value = payload[key]
        if value is None:
            continue
        value = str(value).strip()
        if key in SENSITIVE_KEYS and value == "":
            # 敏感字段留空表示不修改，沿用原值。
            continue
        updates[key] = value

    if updates:
        _write_env(updates)
        # 热更新进程内环境变量，使 get_translator 下次读取即生效。
        for key, value in updates.items():
            os.environ[key] = value

    return get_config_masked()


def resolve_test_config(payload: Dict[str, Optional[str]]) -> Dict[str, str]:
    """为测试连接计算实际生效的配置：提交值优先，敏感字段留空则用已存配置。"""
    current = read_env()

    def pick(key: str, default: str = "") -> str:
        if key in payload and payload[key] is not None:
            value = str(payload[key]).strip()
            if not (key in SENSITIVE_KEYS and value == ""):
                return value
        return os.getenv(key, current.get(key, default))

    return {key: pick(key) for key in CONFIG_KEYS}
