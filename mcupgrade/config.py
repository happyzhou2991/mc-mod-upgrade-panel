# -*- coding: utf-8 -*-
r"""配置与识别缓存读写。

文件默认放在 APP_DIR:
  - 源码运行时:项目根目录
  - 打包成 exe 后:exe 所在目录(方便随包分发、用户可改)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from . import util

if getattr(sys, "frozen", False):       # PyInstaller 打包
    APP_DIR = Path(sys.executable).resolve().parent
else:
    APP_DIR = Path(__file__).resolve().parent.parent

CONFIG_FILE = APP_DIR / "mods_config.json"
MANIFEST_FILE = APP_DIR / "mods_manifest.json"

DEFAULT_CONFIG = {
    "source_mods_folder": "",
    "target_game_version": "26.2",
    "loader": "fabric",
    "out_folder": "",
    "keep_tag_prefix": True,
    "prefer_stable": True,
    "use_github": True,
    "github_token": "",
    "update_resourcepacks": False,
    "update_shaderpacks": False,
    "excluded": [],
    "manual_overrides": {},
    "api_timeout": 30,
    "download_timeout": 60,
    "download_retries": 3,
    "http_proxy": "",
    "https_proxy": "",
    "github_mirrors": [
        "https://gh-proxy.com/",
        "https://ghfast.top/",
        "https://github.moeyy.xyz/",
    ],
}


def load_config():
    if CONFIG_FILE.exists():
        try:
            # utf-8-sig 自动去掉可能的 BOM(有些编辑器会加)
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig"))
            merged = dict(DEFAULT_CONFIG)
            merged.update(data)
            return merged
        except Exception as e:
            util.emit(f"[警告] 读取配置失败({e}),使用默认配置。")
    return dict(DEFAULT_CONFIG)


def save_config(config):
    try:
        CONFIG_FILE.write_text(json.dumps(config, ensure_ascii=False, indent=2),
                               encoding="utf-8")
    except Exception as e:
        util.emit(f"[警告] 保存配置失败: {e}")


def load_manifest():
    if MANIFEST_FILE.exists():
        try:
            return json.loads(MANIFEST_FILE.read_text(encoding="utf-8-sig"))
        except Exception:
            pass
    return {"by_filename": {}, "projects": {}, "github": {}, "versions": {}}


def save_manifest(manifest):
    try:
        MANIFEST_FILE.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        util.emit(f"[警告] 保存识别缓存失败: {e}")
