# -*- coding: utf-8 -*-
"""引擎编排:扫描 → 识别/解析来源 → 下载 → 迁移 → 报告。

CLI 与 GUI 共用:
  - upgrade_mods(source_mods, ...) : 只处理 mod 更新,返回 results
  - run(source_instance, ...)      : 完整流程(含迁移与报告)
"""
from __future__ import annotations

import time
import urllib.parse
from pathlib import Path

from . import config, migrate, report, scan, sources, util

# ---------------------------------------------------------------- Options
def default_migrate_groups():
    """所有迁移分组及默认勾选(取自 scan.EXPORT_GROUPS)。"""
    return {key: default for key, _l, _d, default in scan.EXPORT_GROUPS}


class Options:
    """面板上的勾选项。"""

    def __init__(self, **kw):
        self.update_mods = kw.get("update_mods", True)
        self.use_modrinth = kw.get("use_modrinth", True)
        self.use_github = kw.get("use_github", True)
        mg = default_migrate_groups()
        mg.update(kw.get("migrate_groups") or {})
        self.migrate_groups = mg
        self.update_resourcepacks = kw.get("update_resourcepacks", False)
        self.update_shaderpacks = kw.get("update_shaderpacks", False)
        self.keep_tag_prefix = kw.get("keep_tag_prefix", True)
        self.prefer_stable = kw.get("prefer_stable", True)


def options_from_config(cfg):
    return Options(
        use_github=cfg.get("use_github", True),
        keep_tag_prefix=cfg.get("keep_tag_prefix", True),
        prefer_stable=cfg.get("prefer_stable", True),
    )


def scan_mods_folder(folder, excluded):
    jars, disabled = [], []
    excluded = set(excluded or [])
    for p in sorted(Path(folder).iterdir()):
        if not p.is_file():
            continue
        low = p.name.lower()
        if not low.endswith(".jar"):
            continue
        if low.endswith(".disabled"):
            disabled.append(p)
            continue
        if p.name in excluded:
            disabled.append(p)
            continue
        jars.append(p)
    return jars, disabled


# ---------------------------------------------------------------- mod 更新
def upgrade_mods(source, target, loader, out, cfg, opts, dry_run=False,
                 excluded=None):
    """更新 mod:识别 → 查目标版本 → 下载到 out。返回 (results, disabled)。
    excluded 不传时用 cfg["excluded"];面板会把未勾选迁移的 mod 传进来排除更新。"""
    if excluded is None:
        excluded = cfg.get("excluded", [])
    jars, disabled = scan_mods_folder(source, excluded)
    util.emit(f"[扫描] 共 {len(jars)} 个启用 mod,{len(disabled)} 个忽略(.disabled/排除)")
    if not jars:
        util.emit("[错误] 没有任何要处理的 jar。")
        return [], disabled

    manifest = config.load_manifest()
    identified, not_found = [], []
    util.emit("[识别] 通过 Modrinth 识别 mod 身份 ...")
    for i, jar in enumerate(jars, 1):
        util.emit(f"  ({i}/{len(jars)}) {jar.name[:60]}")
        info = sources.identify_mod(manifest, jar) if opts.use_modrinth else None
        if info is None:
            not_found.append(jar)
        else:
            identified.append((jar, info))
        time.sleep(util.SLEEP)
    config.save_manifest(manifest)
    util.emit(f"[识别] 完成:{len(identified)} 个已识别,{len(not_found)} 个未在 Modrinth 找到")

    results = []

    # ---- 按项目去重后,查目标版本 + 下载(Modrinth) ----
    seen = {}
    for jar, info in identified:
        seen.setdefault(info["project_id"], []).append(jar)
    projects = manifest.get("projects", {})
    total = len(seen)
    for idx, (pid, jar_list) in enumerate(seen.items(), 1):
        info = projects.get(pid, {})
        title = info.get("title") or pid
        slug = info.get("slug", "")
        primary_jar = sorted(jar_list, key=lambda p: p.stat().st_mtime,
                             reverse=True)[0]
        dupes = [p.name for p in jar_list if p != primary_jar]

        util.emit(f"\n[{idx}/{total}] {title} ({slug})")
        vers = sources.query_target_version(pid, target, loader)
        time.sleep(util.SLEEP)
        if opts.prefer_stable and vers:
            stable = [v for v in vers if v.get("version_type") == "release"]
            if stable:
                vers = stable

        if not vers:
            latest = sources.query_latest_supported(pid, loader)
            time.sleep(util.SLEEP)
            note = ("最高支持到 MC " + latest) if latest \
                else "Modrinth 上找不到该加载器版本"
            results.append({
                "status": "no_version", "tag": util.tag_prefix_of(primary_jar.name),
                "title": title, "slug": slug,
                "old_file": primary_jar.name, "new_version": "", "new_file": "",
                "note": note, "duplicates": dupes,
            })
            util.emit(f"  无 {target} 版本。{note}")
            continue

        v = vers[0]
        file_ = sources.pick_main_file(v)
        if not file_:
            results.append({
                "status": "no_version", "tag": util.tag_prefix_of(primary_jar.name),
                "title": title, "slug": slug, "old_file": primary_jar.name,
                "new_version": "", "new_file": "",
                "note": "有版本但无可用文件", "duplicates": dupes,
            })
            util.emit(f"  有 {target} 版本但找不到 jar 文件。")
            continue

        new_filename = file_["filename"]
        dest_name = new_filename
        if opts.keep_tag_prefix:
            dest_name = util.tag_prefix_of(primary_jar.name) + new_filename
        dest_name = util.sanitize_filename(dest_name)
        dest = out / dest_name
        hashes = file_.get("hashes") or {}
        expect_sha1 = hashes.get("sha1")

        entry = {
            "status": "ok", "tag": util.tag_prefix_of(primary_jar.name),
            "title": title, "slug": slug, "old_file": primary_jar.name,
            "new_version": v.get("version_number", ""),
            "new_file": new_filename, "dest_file": dest_name,
            "download_url": file_.get("url", ""), "expected_sha1": expect_sha1,
            "downloaded": False, "verify_mc": None, "note": "", "duplicates": dupes,
        }

        if dry_run:
            util.emit(f"  [dry-run] {new_filename} ← 新版本 {entry['new_version']}")
        else:
            if dest.exists() and expect_sha1 and \
                    util.sha1_of_file(dest).lower() == expect_sha1.lower():
                util.emit(f"  [已存在] {dest_name}(版本一致,跳过下载)")
                entry["downloaded"] = True
            else:
                util.emit(f"  [下载] {dest_name}")
                ok = util.download_file(entry["download_url"], dest, expect_sha1)
                entry["downloaded"] = ok
                if not ok:
                    entry["status"] = "download_failed"
                    entry["note"] = "下载失败,请重跑或手动下载"
            if entry["downloaded"]:
                mc_dep, _ = util.read_fabric_depends(dest)
                entry["verify_mc"] = mc_dep
                entry["verify_ok"] = util.mc_dep_includes(mc_dep, target)
        results.append(entry)

    # ---- 未识别的:manual_overrides → GitHub 自动搜索 → 手动清单 ----
    github_pending = []
    overrides = cfg.get("manual_overrides") or {}
    for jar in not_found:
        override = overrides.get(jar.name)
        if override and override.get("url"):
            _download_override(results, jar, override, target, cfg, opts, out,
                               dry_run)
            continue

        if opts.use_github:
            meta = util.read_fabric_mod_meta(jar)
            mod_name = (meta or {}).get("name") or (meta or {}).get("id") \
                or jar.name
            mod_id = (meta or {}).get("id") or ""
            g = sources.github_resolve(manifest, mod_name, mod_id, target,
                                       loader,
                                       token=cfg.get("github_token", ""))
            config.save_manifest(manifest)
            if g and g.get("ok"):
                new_filename = g["filename"]
                dest_name = new_filename
                if opts.keep_tag_prefix:
                    dest_name = util.tag_prefix_of(jar.name) + new_filename
                dest_name = util.sanitize_filename(dest_name)
                dest = out / dest_name
                entry = {
                    "status": "ok", "tag": util.tag_prefix_of(jar.name),
                    "title": jar.name, "slug": f"github:{g['repo']}",
                    "old_file": jar.name, "new_version": g.get("tag", ""),
                    "new_file": new_filename, "dest_file": dest_name,
                    "download_url": g["url"], "expected_sha1": None,
                    "downloaded": False, "verify_mc": None,
                    "note": "GitHub 自动匹配,请人工确认", "duplicates": [],
                }
                github_pending.append(
                    {"old": jar.name, "repo": g["repo"], "new": new_filename})
                if dry_run:
                    util.emit(f"  [dry-run][GitHub] {new_filename} ← {g['repo']}")
                else:
                    ok = util.download_file(g["url"], dest)
                    entry["downloaded"] = ok
                    if ok:
                        mc_dep, _ = util.read_fabric_depends(dest)
                        entry["verify_mc"] = mc_dep
                        entry["verify_ok"] = util.mc_dep_includes(mc_dep, target)
                    else:
                        entry["status"] = "download_failed"
                        entry["note"] = "GitHub 下载失败"
                results.append(entry)
                continue

            note = (g or {}).get("note", "Modrinth/GitHub 都未找到")
            cands = (g or {}).get("candidates") or []
            if cands:
                note += "；候选:" + "、".join(
                    f"{c['repo']}@{c['tag']}" for c in cands[:3])
            results.append({
                "status": "not_found", "tag": util.tag_prefix_of(jar.name),
                "title": jar.name, "slug": "", "old_file": jar.name,
                "new_version": "", "new_file": "",
                "note": note, "duplicates": [],
            })
            util.emit(f"  [未找到] {jar.name} — {note}")
            continue

        results.append({
            "status": "not_found", "tag": util.tag_prefix_of(jar.name),
            "title": jar.name, "slug": "", "old_file": jar.name,
            "new_version": "", "new_file": "",
            "note": "不在 Modrinth,需手动处理", "duplicates": [],
        })

    return results, disabled, github_pending


def _download_override(results, jar, override, target, cfg, opts, out, dry_run):
    new_filename = util.sanitize_filename(
        override.get("filename")
        or Path(urllib.parse.urlparse(override["url"]).path).name
        or jar.name)
    dest_name = new_filename
    if opts.keep_tag_prefix:
        dest_name = util.tag_prefix_of(jar.name) + new_filename
    dest = out / util.sanitize_filename(dest_name)
    entry = {
        "status": "ok", "tag": util.tag_prefix_of(jar.name),
        "title": jar.name, "slug": "", "old_file": jar.name,
        "new_version": "", "new_file": new_filename, "dest_file": dest.name,
        "download_url": override["url"], "expected_sha1": override.get("sha1"),
        "downloaded": False, "verify_mc": None, "verify_ok": None,
        "note": "手动覆盖来源", "duplicates": [],
    }
    if dry_run:
        util.emit(f"  [dry-run][手动] {dest.name}")
    else:
        ok = util.download_file(override["url"], dest, override.get("sha1"))
        entry["downloaded"] = ok
        if ok:
            mc_dep, _ = util.read_fabric_depends(dest)
            entry["verify_mc"] = mc_dep
            entry["verify_ok"] = util.mc_dep_includes(mc_dep, target)
        else:
            entry["status"] = "download_failed"
            entry["note"] = "手动 URL 下载失败"
    results.append(entry)


# ---------------------------------------------------------------- 完整流程
def _list_names(folder):
    folder = Path(folder)
    if not folder.is_dir():
        return []
    return [p.name for p in sorted(folder.iterdir())]


def run(source_instance, new_instance, target, loader, out, cfg, opts,
        entries=None, dry_run=False, mod_selected=None):
    """完整流程。entries 可来自面板(含用户调整后的动作),否则自动分类。
    mod_selected: {mod文件名: 是否迁移},由面板第 3 页的 mod 自选传入。"""
    source_instance = Path(source_instance)
    out = Path(out)
    if entries is None:
        entries = scan.classify_instance(source_instance)
    util.emit(f"[扫描] 实例目录 {source_instance} 共 {len(entries)} 个条目")

    # ---- 面板未勾选迁移的 mod:排除在更新之外 ----
    excluded = list(cfg.get("excluded", []))
    if mod_selected is not None:
        excluded += [name for name, on in mod_selected.items() if not on]

    results, disabled, github_pending = [], [], []
    mods_folder = source_instance / "mods"
    if opts.update_mods and mods_folder.is_dir():
        results, disabled, github_pending = upgrade_mods(
            mods_folder, target, loader, out, cfg, opts, dry_run,
            excluded=excluded)

    # ---- 资源包/光影 尝试更新(Modrinth)----
    pack_updates = {}
    for grp, folder_name, flag in (("resourcepacks", "resourcepacks",
                                    opts.update_resourcepacks),
                                   ("shaderpacks", "shaderpacks",
                                    opts.update_shaderpacks)):
        if flag:
            r, m = _upgrade_packs(source_instance / folder_name, grp,
                                  target, out, cfg, opts, dry_run)
            pack_updates[grp] = {"results": r, "meta": m}

    # ---- 迁移(按分组勾选 + 扫描动作;mod 按面板自选单独处理)----
    mig_summary = None
    if new_instance:
        actions = {}
        for e in entries:
            grp = e.get("group") or e.get("category")
            if grp == "mods":
                continue        # mod 由 mod_selected 处理
            if (opts.migrate_groups.get(grp)
                    and e.get("action") == "migrate"):
                actions[e["name"]] = "migrate"
        selected_mods = ([n for n, on in (mod_selected or {}).items() if on]
                         if mod_selected is not None else [])
        if actions or selected_mods:
            util.emit(f"[迁移] 选择 {len(actions)} 个文件夹/文件 + "
                      f"{len(selected_mods)} 个 mod 迁移到 {new_instance}")
            if dry_run:
                util.emit("[dry-run][迁移] 不会真的复制,以下将迁移: " +
                          ", ".join(sorted(actions) + sorted(selected_mods)))
                mig_summary = {"copied": 0, "skipped": 0,
                               "migrated": sorted(actions) + sorted(selected_mods),
                               "mods": sorted(selected_mods), "dry_run": True}
            else:
                mig_summary = {"copied": 0, "skipped": 0, "migrated": [], "mods": []}
                if actions:
                    part = migrate.migrate_selected(source_instance,
                                                    new_instance, actions)
                    mig_summary["copied"] += part["copied"]
                    mig_summary["skipped"] += part["skipped"]
                    mig_summary["migrated"].extend(part["migrated"])
                if selected_mods:
                    # 旧文件名 -> out 里的新文件名(更新成功的才用新版)
                    updated = {r["old_file"]: r["dest_file"] for r in results
                               if r.get("status") == "ok" and r.get("downloaded")
                               and r.get("old_file") and r.get("dest_file")}
                    part = migrate.migrate_mods(
                        source_instance / "mods", out,
                        new_instance / "mods", updated, selected_mods)
                    mig_summary["copied"] += part["copied"]
                    mig_summary["skipped"] += part["skipped"]
                    mig_summary["migrated"].extend(part["migrated"])
                    mig_summary["mods"].extend(part["migrated"])
        else:
            util.emit("[迁移] 未选择任何迁移项,只做 mod 升级。")

    # ---- 资源包/光影清单 ----
    rp_list = _list_names(source_instance / "resourcepacks")
    sp_list = _list_names(source_instance / "shaderpacks")

    # ---- 各分组包含的条目(供报告)----
    groups = {}
    for grp, e_list in scan.groups_for_entries(entries).items():
        groups[grp] = {"label": scan.GROUP_LABEL.get(grp, grp),
                       "names": [e["name"] for e in e_list]}

    # ---- 未知条目的最终处理(供报告) ----
    unknown = [{"name": e["name"],
                "action": e.get("action", "ignore")}
               for e in entries if (e.get("group") or e.get("category")) == "other"]

    meta = {
        "source": str(source_instance),
        "target": target, "loader": loader,
        "out": str(out),
        "disabled": [p.name for p in disabled],
        "resourcepacks": rp_list, "shaderpacks": sp_list,
        "github_pending": github_pending,
        "migration": mig_summary, "scan_unknown": unknown,
        "groups": groups, "pack_updates": pack_updates,
        "enabled_groups": [g for g, v in opts.migrate_groups.items() if v],
    }
    report_path = report.write(results, meta, out)
    return {"results": results, "entries": entries, "migration": mig_summary,
            "report": report_path, "meta": meta}


def _upgrade_packs(folder, grp, target, out, cfg, opts, dry_run):
    """资源包/光影文件夹里的 .zip 包在 Modrinth 上尝试更新。
    文件夹形式的包无法哈希识别,只迁移不更新。
    返回 (results条目, meta摘要)。"""
    folder = Path(folder)
    label = scan.GROUP_LABEL.get(grp, grp)
    results, meta = [], {"updated": 0, "skipped": 0,
                         "not_found": [], "folder_packs": []}
    if not folder.is_dir():
        return results, meta
    manifest = config.load_manifest()
    packs = sorted(p for p in folder.iterdir()
                   if p.is_file() and p.suffix.lower() == ".zip")
    folder_packs = sorted(p.name for p in folder.iterdir()
                          if p.is_dir() and not p.name.startswith("."))
    meta["folder_packs"] = folder_packs
    meta["skipped"] = len(folder_packs)
    util.emit(f"[{label}] {len(packs)} 个 zip 包尝试更新,"
              f"{len(folder_packs)} 个文件夹形式(仅迁移)")

    for i, p in enumerate(packs, 1):
        util.emit(f"  ({i}/{len(packs)}) {p.name[:60]}")
        info = sources.identify_mod(manifest, p)
        if info is None:
            meta["not_found"].append(p.name)
            util.emit("    未在 Modrinth 找到,保留原包")
            continue
        pid = info["project_id"]
        vers = sources.query_target_version(pid, target, None)
        time.sleep(util.SLEEP)
        if opts.prefer_stable and vers:
            stable = [v for v in vers if v.get("version_type") == "release"]
            if stable:
                vers = stable
        if not vers:
            meta["not_found"].append(p.name)
            util.emit(f"    无 {target} 版本,保留原包")
            continue
        v = vers[0]
        file_ = sources.pick_main_file(v)
        if not file_:
            meta["not_found"].append(p.name)
            continue
        dest_name = util.sanitize_filename(file_["filename"])
        dest = out / dest_name
        entry = {
            "status": "ok", "title": p.name, "old_file": p.name,
            "new_file": file_["filename"], "dest_file": dest_name,
            "new_version": v.get("version_number", ""),
            "download_url": file_.get("url", ""),
            "expected_sha1": (file_.get("hashes") or {}).get("sha1"),
            "downloaded": False,
            "note": f"{label} Modrinth 更新", "duplicates": [],
        }
        if dry_run:
            util.emit(f"  [dry-run][{label}] {dest_name} ← "
                      f"{v.get('version_number', '')}")
            meta["updated"] += 1
        else:
            if dest.exists() and entry["expected_sha1"] and \
                    util.sha1_of_file(dest).lower() == entry["expected_sha1"].lower():
                util.emit(f"  [已存在] {dest_name}(版本一致,跳过下载)")
                entry["downloaded"] = True
            else:
                util.emit(f"  [下载] {dest_name}")
                ok = util.download_file(entry["download_url"], dest,
                                        entry["expected_sha1"])
                entry["downloaded"] = ok
                if not ok:
                    entry["status"] = "download_failed"
                    entry["note"] = "下载失败,请重跑或手动下载"
            if entry["downloaded"]:
                meta["updated"] += 1
        results.append(entry)

    config.save_manifest(manifest)
    return results, meta
