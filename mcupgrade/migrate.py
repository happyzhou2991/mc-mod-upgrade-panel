# -*- coding: utf-8 -*-
"""迁移:把旧实例的配置/存档等复制到新实例,合并不覆盖。"""
from __future__ import annotations

import shutil
from pathlib import Path

from . import util

# CLI 迁移默认项(面板用扫描分类,不走这个)
DEFAULT_MIGRATE = ["config", "options.txt", "servers.dat", "saves",
                   "resourcepacks", "shaderpacks"]


def _copy_merge(src, dst):
    """把 src 递归复制到 dst:目标已存在的文件跳过不覆盖。
    返回 (复制项数, 跳过项数)。"""
    src, dst = Path(src), Path(dst)
    copied = skipped = 0
    if src.is_dir():
        dst.mkdir(parents=True, exist_ok=True)
        for item in sorted(src.iterdir()):
            c, s = _copy_merge(item, dst / item.name)
            copied += c
            skipped += s
    else:
        if dst.exists():
            return 0, 1
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied += 1
    return copied, skipped


def migrate_selected(old, new, actions):
    """按 {条目名: 动作} 迁移。动作 in {"migrate", "ignore", "mods", "ask"}(只迁移 migrate)。
    返回 {copied, skipped, total} 汇总。"""
    old, new = Path(old), Path(new)
    new.mkdir(parents=True, exist_ok=True)
    total_copied = total_skipped = 0
    done = []
    for name, action in actions.items():
        if action != "migrate":
            continue
        src = old / name
        if not src.exists():
            continue
        try:
            copied, skipped = _copy_merge(src, new / name)
        except Exception as e:
            util.emit(f"  [失败] {name}: {e}")
            continue
        total_copied += copied
        total_skipped += skipped
        done.append(name)
        util.emit(f"  [迁移] {name}: 复制 {copied} 项" +
                  (f",跳过 {skipped} 项(已存在)" if skipped else ""))
    util.emit(f"[迁移] 完成:新复制 {total_copied} 项,跳过 {total_skipped} 项(不覆盖已存在)")
    return {"copied": total_copied, "skipped": total_skipped,
            "migrated": done, "total": total_copied + total_skipped}


def migrate_mods(source_mods, out, dest_mods, updated, selected):
    """把选中的 mod 迁移到新实例的 mods 文件夹。
    updated: {旧文件名: out 里的新文件名};有更新成功的用新版,否则用旧 jar。
    合并不覆盖。返回 {copied, skipped, migrated}。"""
    source_mods = Path(source_mods)
    dest_mods = Path(dest_mods)
    dest_mods.mkdir(parents=True, exist_ok=True)
    copied = skipped = 0
    migrated = []
    for name in sorted(selected):
        new_name = updated.get(name)
        src = Path(out) / new_name if new_name else source_mods / name
        dst = dest_mods / (new_name or name)
        if not src.exists():
            util.emit(f"  [跳过] {name}:源文件不存在")
            continue
        if dst.exists():
            skipped += 1
            util.emit(f"  [迁移] {name}:新实例已有同名文件,跳过(不覆盖)")
            continue
        try:
            shutil.copy2(src, dst)
            copied += 1
            migrated.append(name)
            util.emit(f"  [迁移] {name}" +
                      (f" → {dst.name}(更新版)" if new_name else "(沿用旧版)"))
        except Exception as e:
            util.emit(f"  [失败] {name}: {e}")
    util.emit(f"[迁移] mod 迁移完成:新复制 {copied} 项,跳过 {skipped} 项(不覆盖)")
    return {"copied": copied, "skipped": skipped, "migrated": migrated}
