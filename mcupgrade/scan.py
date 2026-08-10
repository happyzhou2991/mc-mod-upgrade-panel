# -*- coding: utf-8 -*-
"""实例文件夹遍历与条目分类。

每个条目给出:
  category/group : EXPORT_GROUPS 里的分组 key;另加 mods / ignore
  action   : mods(由更新流程处理) | migrate(迁移) | ignore(跳过) | ask(问用户)

规则表可扩展:在 FOLDER_RULES / FILE_RULES 里加一条即可。
"""
from __future__ import annotations

from pathlib import Path

# 导出内容分组: (key, 标签, 说明, 默认勾选)
EXPORT_GROUPS = [
    ("mods",         "模组",           "勾选=迁移到新实例,可逐项取消", True),
    ("settings",     "游戏设置",       "options.txt 键位/音量/视频设置等", True),
    ("personal",     "个人信息",       "命令历史、用户缓存、Realms 数据", True),
    ("maps",         "已绘制的地图",    "journeymap 等地图类 mod 的记录/路标", True),
    ("jei_emi",      "JEI/EMI 个人信息", "物品收藏夹、配方、合成历史", True),
    ("resourcepacks", "资源包/纹理包",  "resourcepacks 文件夹", True),
    ("shaderpacks",  "光影包",         "shaderpacks 文件夹", True),
    ("screenshots",  "截图",           "screenshots 文件夹", True),
    ("structures",   "导出的结构",      "schematics 等投影/原理图", True),
    ("replay",       "录像回放",        "replay_recordings 文件夹", True),
    ("saves",        "单人游戏存档",    "saves 世界/地图", True),
    ("serverlist",   "多人服务器列表",  "servers.dat", True),
    ("config",       "mod 配置",       "config 文件夹", True),
    ("mod_data",     "mod 数据目录",    "baritone/itemscroller 等", True),
    ("other",        "其他文件夹",      "无法自动识别的条目,逐项勾选", False),
]
GROUP_LABEL = {key: label for key, label, _desc, _d in EXPORT_GROUPS}

# 目录分类规则: 名称 -> (group, 中文说明)
FOLDER_RULES = {
    # mods(更新流程处理,是否迁移到新实例在第 3 页逐项勾选)
    "mods": ("mods", "模组文件夹(在第 3 页逐项选择是否迁移)"),
    # 主要迁移目录
    "config": ("config", "配置文件夹"),
    "saves": ("saves", "单人游戏存档"),
    "resourcepacks": ("resourcepacks", "资源包"),
    "texturepacks": ("resourcepacks", "纹理包(旧版本)"),
    "shaderpacks": ("shaderpacks", "光影"),
    "screenshots": ("screenshots", "截图"),
    "schematics": ("structures", "原理图/投影"),
    "structures": ("structures", "导出结构"),
    "replay_recordings": ("replay", "录像回放"),
    # 地图类
    "journeymap": ("maps", "旅行地图数据"),
    "voxelmap": ("maps", "小地图数据"),
    "xaero": ("maps", "Xaero 地图数据"),
    # JEI / EMI 数据
    "emi": ("jei_emi", "EMI 数据"),
    "jei": ("jei_emi", "JEI 数据"),
    # mod 数据目录(可迁移)
    "baritone": ("mod_data", "Baritone 数据"),
    "chesttracker": ("mod_data", "箱子追踪数据"),
    "itemscroller": ("mod_data", "物品滚轮数据"),
    "litematica-preview-cache": ("mod_data", "投影预览缓存"),
    "litematica": ("mod_data", "投影数据"),
    "tweakeroo": ("mod_data", "Tweakeroo 数据"),
    "minihud": ("mod_data", "迷你HUD数据"),
    "malilib": ("mod_data", "malilib 数据"),
    "litematica_printer": ("mod_data", "投影打印数据"),
    "data": ("mod_data", "mod 数据目录"),
    # 忽略
    "logs": ("ignore", "日志"),
    "crash-reports": ("ignore", "崩溃报告"),
    ".fabric": ("ignore", "Fabric 运行时"),
    ".mixin.out": ("ignore", "Mixin 输出"),
    ".bobby": ("ignore", "Bobby 缓存"),
    ".replay_cache": ("ignore", "回放缓存"),
    "debug": ("ignore", "调试文件"),
    "downloads": ("ignore", "下载"),
    "libraries": ("ignore", "依赖库"),
    "assets": ("ignore", "游戏资源"),
    "versions": ("ignore", "版本核心"),
    "backups": ("ignore", "备份"),
    "natives-windows-x86_64": ("ignore", "原生库"),
    "native": ("ignore", "原生库"),
    "patched_obfuscated_namespaces": ("ignore", "运行时生成"),
}

# 文件分类规则: 名称(小写) -> (group, 中文说明)
FILE_RULES = {
    "options.txt": ("settings", "键位/音量/视频设置"),
    "optionsof.txt": ("settings", "视频设置(OptiFine 类)"),
    "command_history.txt": ("personal", "命令历史"),
    "usercache.json": ("personal", "用户缓存"),
    "realms_persistence.json": ("personal", "Realms 数据"),
    "servers.dat": ("serverlist", "服务器列表"),
    "servers.dat_old": ("serverlist", "服务器列表备份"),
    "emi.json": ("jei_emi", "EMI 收藏夹/合成历史"),
    "log4j2.xml": ("settings", "日志配置"),
    "debug-profile.json": ("settings", "调试配置文件"),
    "authlib-injector.log": ("ignore", "登录器日志"),
    # .disabled 结尾的模组文件
}

# 扩展名启发(仅用于未知文件)
IGNORE_EXT = {".log", ".tmp", ".zip", ".bak"}
CONFIG_EXT = {".json", ".txt", ".dat", ".properties", ".xml", ".toml", ".yaml"}

# 分组 -> 默认动作
ACTION_FOR_GROUP = {
    "mods": "mods",
    "config": "migrate",
    "saves": "migrate",
    "resourcepacks": "migrate",
    "shaderpacks": "migrate",
    "screenshots": "migrate",
    "structures": "migrate",
    "replay": "migrate",
    "maps": "migrate",
    "jei_emi": "migrate",
    "settings": "migrate",
    "personal": "migrate",
    "serverlist": "migrate",
    "mod_data": "migrate",
    "ignore": "ignore",
}


def _classify(name, is_dir, jar_stems=None):
    """返回 (group, label, action)。jar_stems 是顶层版本 jar 的 stem 集合。"""
    low = name.lower()
    if is_dir:
        if low in FOLDER_RULES:
            grp, label = FOLDER_RULES[low]
        elif low.endswith("-natives"):
            return "ignore", "原生库", "ignore"
        else:
            return "other", "未知文件夹", "ask"
    else:
        if low in FILE_RULES:
            grp, label = FILE_RULES[low]
        else:
            ext = Path(name).suffix.lower()
            if low.endswith(".jar.disabled"):
                return "ignore", "已禁用模组", "ignore"
            if low.endswith(".jar"):
                return "ignore", "版本核心 jar", "ignore"
            if ext in IGNORE_EXT:
                return "ignore", "临时/日志类", "ignore"
            if ext in CONFIG_EXT:
                # 版本元数据 json(与顶层版本 jar 同名)→ 忽略
                if (ext == ".json" and jar_stems
                        and Path(name).stem.lower() in jar_stems):
                    return "ignore", "版本元数据", "ignore"
                return "config", "配置文件", "migrate"
            return "other", "未知文件", "ask"

    action = ACTION_FOR_GROUP.get(grp, "ask")
    return grp, label, action


def classify_instance(folder):
    """遍历实例文件夹顶层条目,返回 entries 列表。"""
    folder = Path(folder)
    entries = []
    if not folder.is_dir():
        return entries
    jar_stems = {p.stem.lower() for p in folder.iterdir()
                 if p.is_file() and p.suffix.lower() == ".jar"}
    for p in sorted(folder.iterdir()):
        try:
            grp, label, action = _classify(p.name, p.is_dir(), jar_stems)
            entries.append({"name": p.name, "is_dir": p.is_dir(),
                            "category": grp, "group": grp,
                            "category_label": label, "action": action})
        except OSError:
            entries.append({"name": p.name, "is_dir": False,
                            "category": "other", "group": "other",
                            "category_label": "无法访问", "action": "ask"})
    return entries


def groups_for_entries(entries):
    """把扫描结果按分组聚合,返回 {group_key: [entry, ...]}。"""
    groups = {}
    for e in entries:
        groups.setdefault(e.get("group") or e.get("category"), []).append(e)
    return groups
