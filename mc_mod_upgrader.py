#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mc_mod_upgrader.py —— Minecraft Fabric 模组升级工具(命令行版)

这是 mcupgrade 引擎的 CLI 入口;图形面板请用 panel.py。

用法:
  python mc_mod_upgrader.py upgrade --source <mods文件夹> --game-version 26.2 --loader fabric [--out <目录>] [--dry-run]
  python mc_mod_upgrader.py migrate --old <旧实例目录> --new <新实例目录>
  无参数运行时进入交互模式。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from mcupgrade import config, engine, migrate, report, util
from mcupgrade import __version__


def cmd_upgrade(args):
    cfg = config.load_config()
    source = Path(args.source or cfg.get("source_mods_folder") or "")
    target = args.game_version or cfg.get("target_game_version", "26.2")
    loader = args.loader or cfg.get("loader", "fabric")
    out = Path(args.out or cfg.get("out_folder")
               or config.APP_DIR / "output" / f"mods-{target}")

    if not source.is_dir():
        print(f"[错误] 来源 mods 文件夹不存在: {source}")
        print("       用 --source 指定,例如:")
        print('       python mc_mod_upgrader.py upgrade --source "<旧实例>/mods" --game-version 26.2')
        sys.exit(1)

    print(f"== 来源 mods 文件夹: {source}")
    print(f"== 目标 MC 版本: {target}   加载器: {loader}")
    print(f"== 输出目录:   {out}")

    opts = engine.options_from_config(cfg)
    results, disabled, github_pending = engine.upgrade_mods(
        source, target, loader, out, cfg, opts, args.dry_run)

    meta = {
        "source": str(source), "target": target, "loader": loader,
        "out": str(out), "disabled": [p.name for p in disabled],
        "resourcepacks": [], "shaderpacks": [],
        "github_pending": github_pending, "migration": None, "scan_unknown": [],
    }
    report_path = report.write(results, meta, out)

    cfg["source_mods_folder"] = str(source)
    cfg["out_folder"] = str(out)
    config.save_config(cfg)

    print("\n" + "=" * 50)
    print(f"完成!报告已生成:{report_path}")
    report.print_summary(results)


def cmd_migrate(args):
    old, new = Path(args.old), Path(args.new)
    if not old.is_dir():
        print(f"[错误] 旧实例目录不存在: {old}")
        sys.exit(1)
    print("== 从旧实例迁移配置到新实例(合并不覆盖) ==")
    print(f"   旧: {old}")
    print(f"   新: {new}")
    actions = {name: "migrate" for name in migrate.DEFAULT_MIGRATE}
    migrate.migrate_selected(old, new, actions)


def _ask(prompt, default=""):
    try:
        val = input(prompt).strip()
        return val or default
    except (EOFError, KeyboardInterrupt):
        print("\n[已取消]")
        sys.exit(0)


def cmd_interactive():
    cfg = config.load_config()
    print("== MC 模组升级工具(交互模式)==")
    print("(直接回车使用中括号里的默认值)")

    src_default = cfg.get("source_mods_folder", "")
    src = _ask(f"来源 mods 文件夹 [{src_default or '必填'}]: ", src_default)
    if not src:
        print("[错误] 必须提供来源文件夹。")
        sys.exit(1)
    tgt = _ask(f"目标 MC 版本 [{cfg.get('target_game_version', '26.2')}]: ",
               cfg.get("target_game_version", "26.2"))
    loader = _ask(f"加载器 [fabric]: ", "fabric")
    out_default = cfg.get("out_folder") or str(config.APP_DIR / "output" / f"mods-{tgt}")
    out = _ask(f"输出目录 [{out_default}]: ", out_default)

    cmd_upgrade(argparse.Namespace(source=src, game_version=tgt, loader=loader,
                                   out=out, dry_run=False))


def main():
    util.utf8_console()
    parser = argparse.ArgumentParser(
        prog="mc_mod_upgrader",
        description="Minecraft Fabric 模组升级工具(命令行版)。")
    parser.add_argument("--version", action="version",
                        version=f"mc-mod-upgrade-panel {__version__}")
    sub = parser.add_subparsers(dest="command")

    p_up = sub.add_parser("upgrade", help="识别并下载目标 MC 版本的 mod")
    p_up.add_argument("--source", help="来源 mods 文件夹(默认读配置)")
    p_up.add_argument("--game-version", help="目标 MC 版本,如 26.2")
    p_up.add_argument("--loader", help="加载器,如 fabric")
    p_up.add_argument("--out", help="输出目录")
    p_up.add_argument("--dry-run", action="store_true",
                      help="只识别和查版本,不下载")

    p_mig = sub.add_parser("migrate", help="把旧实例配置迁移到新实例")
    p_mig.add_argument("--old", required=True, help="旧实例目录")
    p_mig.add_argument("--new", required=True, help="新实例目录")

    args = parser.parse_args()
    if args.command == "upgrade":
        cmd_upgrade(args)
    elif args.command == "migrate":
        cmd_migrate(args)
    else:
        cmd_interactive()


if __name__ == "__main__":
    main()
