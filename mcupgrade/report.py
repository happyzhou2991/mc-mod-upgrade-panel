# -*- coding: utf-8 -*-
"""中文报告生成(report.md / report.json)。"""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import __version__


def _status_ver(r, target):
    vok = r.get("verify_ok")
    raw = r.get("verify_mc")
    if vok is True:
        return f"{target} ✓"
    if vok is False:
        return f"不含{target}(声明 {raw})"
    if raw:
        return f"(未声明依赖:{raw})"
    return "(未声明)"


def _group_migrated(groups, migrated):
    """把已迁移的条目按分组标签归类,返回 {标签: [名称…]}。"""
    mig_set = set(migrated)
    out = {}
    for info in groups.values():
        hit = [n for n in info.get("names", []) if n in mig_set]
        if hit:
            out.setdefault(info.get("label", ""), []).extend(hit)
    return out


def build(results, meta):
    ok = [r for r in results if r["status"] == "ok"]
    nov = [r for r in results if r["status"] == "no_version"]
    nf = [r for r in results if r["status"] == "not_found"]
    dlf = [r for r in results if r["status"] == "download_failed"]
    target = meta.get("target", "")

    L = [f"# Mod 升级报告 ({target})", ""]
    L.append(f"- 工具版本: {__version__}")
    L.append(f"- 来源: `{meta.get('source', '')}`")
    L.append(f"- 目标 MC 版本: `{target}`  加载器: `{meta.get('loader', '')}`")
    L.append(f"- 生成时间: {time.strftime('%Y-%m-%d %H:%M')}")
    if meta.get("cancelled"):
        L.append("")
        L.append("> ⏹ **本次运行已取消**,仅完成部分下载;以下为已完成部分的结果。")
    L.append("")
    L.append("## 汇总")
    L.append("")
    L.append(f"- ✅ 已更新/已就绪: **{len(ok)}**")
    L.append(f"- ⚠️ 无 {target} 版本: **{len(nov)}**")
    L.append(f"- ❌ 需手动处理: **{len(nf)}**")
    L.append(f"- 💥 下载失败: **{len(dlf)}**")
    disabled = meta.get("disabled", [])
    if disabled:
        L.append(f"- 🔒 已忽略(.disabled/排除): **{len(disabled)}**")
    mig = meta.get("migration")
    if mig:
        L.append(f"- 📦 迁移: 复制 **{mig['copied']}** 项,跳过 **{mig['skipped']}** 项")
    L.append("")

    # 导出内容分组
    groups = meta.get("groups", {})
    enabled = set(meta.get("enabled_groups", []))
    shown = [(k, v) for k, v in groups.items() if k not in ("mods", "ignore")]
    if shown:
        L.append("## 📦 导出内容分组")
        L.append("")
        L.append("| 分组 | 内容 | 勾选 |")
        L.append("|---|---|---|")
        for k, v in shown:
            items = "、".join(v["names"]) if v.get("names") else "-"
            mark = "✅" if k in enabled else "☐"
            L.append(f"| {v.get('label', k)} | {items} | {mark} |")
        L.append("")

    # GitHub 自动匹配待确认
    gp = meta.get("github_pending", [])
    if gp:
        L.append("## 🤖 GitHub 自动匹配(请人工确认)")
        L.append("")
        L.append("以下 mod 是工具按名字在 GitHub 上自动搜到并下载的,"
                 "**可能匹配错**,请启动游戏前核对。")
        L.append("")
        L.append("| 原 mod | 来源仓库 | 匹配文件 |")
        L.append("|---|---|---|")
        for g in gp:
            L.append(f"| {g['old']} | `{g['repo']}` | {g['new']} |")
        L.append("")

    L.append(f"## ✅ 已更新 / 已就绪 ({len(ok)})")
    L.append("")
    L.append("| Mod | 旧文件 | 新文件 | 校验 | 说明 |")
    L.append("|---|---|---|---|---|")
    for r in ok:
        notes = []
        if r.get("duplicates"):
            notes.append("含重复文件:" + ",".join(r["duplicates"]))
        if r.get("note"):
            notes.append(r["note"])
        L.append(f"| {r.get('tag', '')}{r.get('title', '')} | {r.get('old_file', '')} | "
                 f"{r.get('dest_file', '')} | {_status_ver(r, target)} | "
                 f"{'；'.join(notes)} |")
    L.append("")

    if nov:
        L.append(f"## ⚠️ 无 {target} 版本 ({len(nov)})")
        L.append("")
        L.append("这些 mod 暂时没有该 MC 版本的 Fabric 版本,需要你自己决定:"
                 "等更新 / 找替代 / 先不带。")
        L.append("")
        L.append("| Mod | 旧文件 | 说明 |")
        L.append("|---|---|---|")
        for r in nov:
            L.append(f"| {r.get('tag', '')}{r.get('title', '')} | "
                     f"{r.get('old_file', '')} | {r.get('note', '')} |")
        L.append("")

    if nf:
        L.append("## ❌ 需手动处理")
        L.append("")
        L.append("这些 mod 在 Modrinth 和 GitHub 上都自动找不到目标版本,"
                 "需要你手动到原出处找。")
        L.append("")
        L.append("| 文件名 | 说明 |")
        L.append("|---|---|")
        for r in nf:
            L.append(f"| {r.get('old_file', '')} | {r.get('note', '')} |")
        L.append("")

    if dlf:
        L.append("## 💥 下载失败")
        L.append("")
        L.append("| 文件 | 说明 |")
        L.append("|---|---|")
        for r in dlf:
            L.append(f"| {r.get('new_file', '')} | {r.get('note', '')} |")
        L.append("")

    for key, title in (("resourcepacks", "资源包"), ("shaderpacks", "光影")):
        items = meta.get(key, [])
        if items:
            L.append(f"## 🎨 {title}(已迁移,需自行检查更新) ({len(items)})")
            L.append("")
            L.append("| 名称 |")
            L.append("|---|")
            for it in items:
                L.append(f"| {it} |")
            L.append("")

    if disabled:
        L.append("## 🔒 未启用 / 排除的 mod")
        L.append("")
        L.append("(.disabled 文件,或你在面板第 3 页取消勾选的 mod,既不更新也不迁移)")
        L.append("")
        L.append("| 文件名 |")
        L.append("|---|")
        for p in disabled:
            L.append(f"| {p} |")
        L.append("")

    if mig:
        L.append("## 📦 迁移结果")
        L.append("")
        L.append(f"- 新复制 {mig['copied']} 项,跳过 {mig['skipped']} 项(不覆盖已存在的)")
        migrated_by_group = _group_migrated(groups, mig.get("migrated", []))
        if mig.get("mods"):
            migrated_by_group["模组"] = mig["mods"]
        if migrated_by_group:
            L.append("- 按分组:")
            for label, names in migrated_by_group.items():
                L.append(f"  - **{label}**: " + "、".join(names))
        elif mig.get("migrated"):
            L.append("- 已迁移: " + ", ".join(mig["migrated"]))
        L.append("")

    unknown = meta.get("scan_unknown", [])
    if unknown:
        L.append("## ❓ 无法识别、已忽略的条目")
        L.append("")
        L.append("| 名称 | 处理 |")
        L.append("|---|---|")
        for u in unknown:
            L.append(f"| {u['name']} | {u['action']} |")
        L.append("")

    # 资源包/光影 更新
    pack_updates = meta.get("pack_updates", {})
    if pack_updates:
        L.append("## 🆕 资源包 / 光影 更新")
        L.append("")
        for grp, pu in pack_updates.items():
            label = "资源包" if grp == "resourcepacks" else "光影"
            m = pu.get("meta", {})
            L.append(f"### {label}")
            L.append(f"- 更新 **{m.get('updated', 0)}** 个;"
                     f"未找到项目 **{len(m.get('not_found', []))}** 个;"
                     f"文件夹形式仅迁移 **{len(m.get('folder_packs', []))}** 个")
            if m.get("not_found"):
                L.append("- 未找到更新: " + "、".join(m["not_found"]))
            if m.get("folder_packs"):
                L.append("- 仅迁移(文件夹形式,不更新): " + "、".join(m["folder_packs"]))
            L.append("")

    L.append("## 下一步")
    L.append("")
    mig = meta.get("migration")
    steps = []
    if mig and mig.get("migrated"):
        steps.append("选中的 mod 已自动复制进新实例的 mods 文件夹(优先用更新后的版本)")
    steps.append(f"把 `{meta.get('out', '')}` 里还没用到的 jar 补进新实例的 mods 文件夹")
    steps.append("若未做迁移,把旧实例的 config/存档复制进新实例")
    steps.append("核对上面 🤖 GitHub 自动匹配的项")
    steps.append("启动游戏测试")
    for i, s in enumerate(steps, 1):
        L.append(f"{i}. {s}")
    L.append("")

    md = "\n".join(L) + "\n"
    json_obj = {"results": results, "meta": {k: v for k, v in meta.items()
                                             if k not in ("disabled",)}}
    return md, json_obj


def write(results, meta, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    md, json_obj = build(results, meta)
    (out / "report.md").write_text(md, encoding="utf-8")
    (out / "report.json").write_text(
        json.dumps(json_obj, ensure_ascii=False, indent=2), encoding="utf-8")
    return out / "report.md"


def print_summary(results):
    ok = [r for r in results if r["status"] == "ok"]
    nov = [r for r in results if r["status"] == "no_version"]
    nf = [r for r in results if r["status"] == "not_found"]
    dlf = [r for r in results if r["status"] == "download_failed"]
    print(f"  ✅ 已更新/已就绪      : {len(ok)}")
    print(f"  ⚠️ 无目标版本         : {len(nov)}")
    print(f"  ❌ 需手动处理         : {len(nf)}")
    print(f"  💥 下载失败           : {len(dlf)}")
