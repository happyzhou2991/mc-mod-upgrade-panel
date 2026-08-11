#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
panel.py —— MC 模组升级面板(Tkinter 图形版,正式版)

给其他人用:选旧实例 → 扫描分类 → 勾选迁移项 → 升级 → 看报告。
引擎在 mcupgrade 包里,CLI 版见 mc_mod_upgrader.py。
"""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from mcupgrade import config, engine, report, scan, util
from mcupgrade import __version__

ACTION_LABEL = {"migrate": "迁移", "ignore": "忽略", "mods": "模组(更新)",
                "ask": "❓未决定"}


class PanelApp:
    def __init__(self, root):
        self.root = root
        self.cfg = config.load_config()
        self.entries = []            # 扫描结果 [{name,is_dir,category,group,category_label,action}]
        self.mod_selected = {}       # mod 文件名 -> 是否迁移(第 3 页自选)
        self.mod_vars = {}           # mod 文件名 -> 勾选变量
        self.q = queue.Queue()
        self.running = False
        self.last_report = None
        util.set_message_handler(self.q.put)
        self._build_ui()
        self._load_defaults()
        root.after(120, self._drain)

    # ------------------------------------------------------------ UI
    def _build_ui(self):
        self.root.title(f"MC 模组升级面板 {__version__}")
        self.root.geometry("860x640")
        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill="both", expand=True, padx=6, pady=6)
        nb = self.nb

        # 1. 设置
        t1 = ttk.Frame(nb, padding=10)
        nb.add(t1, text=" 1. 设置 ")
        guide = ttk.LabelFrame(t1, padding=6)
        guide.grid(row=0, column=0, columnspan=4, sticky="we", pady=(0, 8))
        ttk.Label(guide, text="三步完成升级:① 填信息 → ② 扫描 → ③ 勾选更新/迁移项 → ④ 开始",
                  font=("", 10, "bold"), foreground="#1a6b1a").pack(anchor="w")
        ttk.Label(guide, text="第一次用:只填「旧实例文件夹」,其余保持默认,点「扫描实例文件夹」即可。",
                  foreground="#555").pack(anchor="w")
        self.var_instance = tk.StringVar()
        self.var_target = tk.StringVar(value="26.2")
        self.var_loader = tk.StringVar(value="fabric")
        self.var_dryrun = tk.BooleanVar(value=False)
        self._row(t1, 1, "旧实例文件夹", self.var_instance,
                  self._browse_instance, "旧版本所在实例(内含 mods/config 等)")
        self._row(t1, 2, "目标 MC 版本", self.var_target, None,
                  "要升到的版本,如 26.2;填旧版本=只在同版本内找最新")
        self._row_combo(t1, 3, "加载器", self.var_loader,
                        ["fabric", "neoforge", "forge", "quilt"])
        ttk.Label(t1, text="加载器要与启动器里选的一致,一般默认 fabric 即可。",
                  foreground="#888").grid(row=3, column=2, columnspan=3, sticky="w")
        ttk.Checkbutton(t1, text="演练模式(不下载、不迁移,只预览结果,新手建议先试一次)",
                        variable=self.var_dryrun).grid(row=4, column=1, sticky="w")
        ttk.Button(t1, text="② 扫描实例文件夹", command=self._do_scan).grid(
            row=5, column=1, sticky="w", pady=8)
        ttk.Label(t1, text="填完上面 3 项点这个按钮,扫描后会跳到第 2 页;第 3 页再勾选更新/迁移项。",
                  foreground="#666").grid(row=6, column=1, sticky="w")

        # 2. 扫描与迁移
        t2 = ttk.Frame(nb, padding=6)
        nb.add(t2, text=" 2. 扫描与迁移 ")
        self._guide(t2, "第二步:确认要迁移的内容(一般直接去第 3 页即可)",
                    "双击一行可切换「迁移 / 忽略」。无法识别的条目在第 3 页『其他文件夹』逐个勾选;"
                    "mod 的迁移/忽略也在第 3 页勾选。")
        tree_frame = ttk.Frame(t2)
        tree_frame.pack(fill="both", expand=True, pady=4)
        cols = ("name", "cat", "label", "action")
        self.tree = ttk.Treeview(tree_frame, columns=cols, show="headings")
        heads = {"name": "名称", "cat": "分类", "label": "说明", "action": "处理"}
        widths = {"name": 240, "cat": 130, "label": 210, "action": 90}
        for c in cols:
            self.tree.heading(c, text=heads[c])
            self.tree.column(c, width=widths[c], anchor="w")
        vs = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", self._toggle_action)

        # 3. 更新选项
        t3 = ttk.Frame(nb, padding=8)
        nb.add(t3, text=" 3. 更新选项 ")
        self.var_mr = tk.BooleanVar(value=True)
        self.var_gh = tk.BooleanVar(value=self.cfg.get("use_github", True))
        self.var_up_rp = tk.BooleanVar(
            value=self.cfg.get("update_resourcepacks", False))
        self.var_up_sp = tk.BooleanVar(
            value=self.cfg.get("update_shaderpacks", False))
        self.var_new_instance = tk.StringVar()
        self.var_out = tk.StringVar()

        self._guide(t3, "第三步:勾选更新与迁移项,填好目标,再去第 4 页开始",
                    "通常保持默认:模组全选、Modrinth 勾选、导出内容全选,再填「新实例文件夹」。")

        f_src = ttk.LabelFrame(t3, text="mod 更新来源", padding=6)
        f_src.pack(fill="x")
        ttk.Checkbutton(f_src, text="Modrinth 自动更新(推荐,能按哈希精准识别)",
                        variable=self.var_mr).pack(anchor="w")
        ttk.Checkbutton(f_src, text="GitHub 自动搜索(Modrinth 找不到时,结果需人工确认)",
                        variable=self.var_gh).pack(anchor="w")

        f_pack = ttk.LabelFrame(t3, text="资源包 / 光影 是否更新(可选)", padding=6)
        f_pack.pack(fill="x", pady=(6, 0))
        ttk.Checkbutton(f_pack, text="更新资源包:在 Modrinth 上查找新版 zip",
                        variable=self.var_up_rp).pack(anchor="w")
        ttk.Checkbutton(f_pack, text="更新光影包:在 Modrinth 上查找新版 zip",
                        variable=self.var_up_sp).pack(anchor="w")
        ttk.Label(f_pack, text="只对 zip 格式的包生效;文件夹形式的资源包/光影只会迁移、不会更新。",
                  foreground="#888").pack(anchor="w")

        self.groups_frame = ttk.LabelFrame(
            t3, text="导出内容(勾选 = 迁移到新实例;不勾 = 不迁移)", padding=6)
        self.groups_frame.pack(fill="both", expand=True, pady=6)
        self.groups_inner = None
        self._groups_hint()

        f_dst = ttk.LabelFrame(t3, text="目标", padding=6)
        f_dst.pack(fill="x")
        self._row(f_dst, 0, "新实例文件夹", self.var_new_instance,
                  self._browse_new, "选中的内容(含 mod)会复制到这里;不填=只升级 mod、不迁移")
        self._row(f_dst, 1, "mod 输出目录", self.var_out, self._browse_out,
                  "升级后的 mod、更新包和报告放这里(不填会自动生成)")

        # 4. 日志与结果
        t4 = ttk.Frame(nb, padding=6)
        nb.add(t4, text=" 4. 日志与结果 ")
        self._guide(t4, "第四步:确认前面 3 页填好后,点「④ 开始升级」",
                    "升级会联网下载新 mod,请保持网络畅通;完成后可打开输出文件夹和报告。")
        bar = ttk.Frame(t4)
        bar.pack(side="bottom", fill="x", pady=4)
        self.btn_start = ttk.Button(bar, text="④ 开始升级", command=self._on_start)
        self.btn_start.pack(side="left")
        self.btn_cancel = ttk.Button(bar, text="取消", state="disabled",
                                     command=self._on_cancel)
        self.btn_cancel.pack(side="left", padx=6)
        ttk.Label(bar, text=" 开始前请确认:旧实例✓ 目标版本✓ 第 3 页勾选✓",
                  foreground="#666").pack(side="left")
        self.btn_open = ttk.Button(bar, text="打开输出文件夹", state="disabled",
                                   command=self._open_out)
        self.btn_open.pack(side="left", padx=6)
        self.btn_report = ttk.Button(bar, text="打开报告", state="disabled",
                                     command=self._open_report)
        self.btn_report.pack(side="left")
        self.lbl_status = ttk.Label(bar, text="", foreground="#555")
        self.lbl_status.pack(side="right")
        self.log = tk.Text(t4, height=16, state="disabled", wrap="word",
                           font=("Microsoft YaHei UI", 9))
        log_sb = ttk.Scrollbar(t4, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=log_sb.set)
        self.log.pack(side="left", fill="both", expand=True)
        log_sb.pack(side="right", fill="y")

    def _row(self, parent, row, label, var, browse_cmd, hint):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=3)
        e = ttk.Entry(parent, textvariable=var)
        e.grid(row=row, column=1, sticky="we", padx=4)
        if browse_cmd:
            ttk.Button(parent, text="浏览", command=browse_cmd).grid(
                row=row, column=2, sticky="w")
        if hint:
            ttk.Label(parent, text=hint, foreground="#888").grid(
                row=row, column=3, sticky="w", padx=6)
        parent.columnconfigure(1, weight=1)

    def _row_combo(self, parent, row, label, var, values):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=3)
        ttk.Combobox(parent, textvariable=var, values=values, width=18).grid(
            row=row, column=1, sticky="w", padx=4)

    def _guide(self, parent, title, sub):
        """页面顶部的引导横幅(用于 pack 布局的页面)。"""
        box = ttk.LabelFrame(parent, padding=6)
        box.pack(fill="x", pady=(0, 8))
        ttk.Label(box, text=title, font=("", 10, "bold"),
                  foreground="#1a6b1a").pack(anchor="w")
        ttk.Label(box, text=sub, foreground="#555").pack(anchor="w")
        return box

    # ------------------------------------------------------------ 导出内容分组
    def _groups_hint(self):
        self.groups_inner = None
        ttk.Label(self.groups_frame,
                  text="先在第 1 页扫描实例,这里会列出能导出/迁移的内容分组。",
                  foreground="#666").pack(anchor="w", pady=8)

    def _make_scroll(self, parent):
        """返回可滚动的内层 Frame(canvas + 滚动条)。

        height=1:让 canvas 只请求 1px 高,实际高度由父容器 expand 分配。
        否则 canvas 默认请求 ~265px,会把同页其他固定内容(如『目标』栏)挤到看不见。"""
        canvas = tk.Canvas(parent, highlightthickness=0, height=1)
        vs = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        wid = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=vs.set)
        canvas.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        for w in (canvas, inner):
            w.bind("<MouseWheel>",
                   lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"))
        # 鼠标停在任意子控件(勾选框/说明文字)上时也能滚轮滚动:
        # 全局监听滚轮,仅当指针落在本 canvas 屏幕矩形内才滚动它,不干扰其他页。
        def _on_mousewheel(event):
            try:
                x0, y0 = canvas.winfo_rootx(), canvas.winfo_rooty()
                inside = (x0 <= event.x_root <= x0 + canvas.winfo_width()
                          and y0 <= event.y_root <= y0 + canvas.winfo_height())
            except Exception:
                return
            if inside:
                canvas.yview_scroll(int(-event.delta / 120), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfigure(wid, width=e.width))
        return inner

    def _rebuild_groups(self):
        """扫描后重建第 3 页的导出内容分组清单。"""
        for w in self.groups_frame.winfo_children():
            w.destroy()
        self.groups_inner = None
        self.group_vars = {}
        self.other_vars = {}
        self.mod_vars = {}
        self.mod_selected = {}
        # 列出旧实例 mods 文件夹里的 jar,默认全部勾选迁移
        mods_dir = Path(self.var_instance.get().strip()) / "mods"
        if mods_dir.is_dir():
            for p in sorted(mods_dir.iterdir()):
                if p.is_file() and p.name.lower().endswith(".jar"):
                    self.mod_selected[p.name] = True
        inner = self._make_scroll(self.groups_frame)
        self.groups_inner = inner
        grouped = scan.groups_for_entries(self.entries)

        for key, label, desc, default in scan.EXPORT_GROUPS:
            e_list = grouped.get(key)
            if not e_list or key == "ignore":
                continue
            gf = ttk.Frame(inner)
            gf.pack(fill="x", anchor="w", pady=2)
            if key == "mods":
                self._build_mods_group(gf, label)
            elif key == "other":
                self._build_other_group(gf, label, e_list)
            else:
                var = tk.BooleanVar(value=default)
                self.group_vars[key] = var
                ttk.Checkbutton(gf, text=f"{label} · {desc}",
                                variable=var).pack(anchor="w")
                ttk.Label(gf, foreground="#666", wraplength=560,
                          text="    包含: " + "、".join(e["name"] for e in e_list)
                          ).pack(anchor="w")

    def _build_other_group(self, parent, label, e_list):
        """无法识别的条目:逐个勾选,分组头 = 全选/全不选。默认不迁移。"""
        master = tk.BooleanVar(value=False)
        self.group_vars["other"] = master
        ttk.Checkbutton(parent, text=f"{label} · 无法识别,逐个勾选要迁移的",
                        variable=master,
                        command=lambda: self._toggle_all_other(master)
                        ).pack(anchor="w")
        for e in e_list:
            v = tk.BooleanVar(value=False)
            self.other_vars[e["name"]] = v
            e["action"] = "ignore"          # 默认不迁移
            name_txt = e["name"] + ("/" if e["is_dir"] else "")
            ttk.Checkbutton(parent, text="    " + name_txt, variable=v,
                            command=lambda n=e["name"], vv=v: self._set_other(n, vv)
                            ).pack(anchor="w")
            self._refresh_tree_row(e["name"])

    def _build_mods_group(self, parent, label):
        """模组:逐个勾选是否迁移到新实例,分组头 = 全选/全不选。默认全选。"""
        master = tk.BooleanVar(value=True)
        self.group_vars["mods"] = master
        ttk.Checkbutton(parent, text=f"{label} · 勾选=迁移到新实例,取消=不迁移",
                        variable=master,
                        command=lambda: self._toggle_all_mods(master)
                        ).pack(anchor="w")
        if not self.mod_selected:
            ttk.Label(parent, foreground="#888",
                      text="    没找到旧实例的 mods 文件夹,或里面没有 mod。"
                      ).pack(anchor="w")
            return
        for name in sorted(self.mod_selected):
            v = tk.BooleanVar(value=self.mod_selected[name])
            self.mod_vars[name] = v
            ttk.Checkbutton(parent, text="    " + name, variable=v,
                            command=lambda n=name, vv=v: self._set_mod(n, vv)
                            ).pack(anchor="w")
        ttk.Label(parent, foreground="#888", wraplength=560,
                  text="    勾选的 mod 会更新并复制到新实例 mods 文件夹;"
                       "取消勾选则既不更新也不复制。"
                  ).pack(anchor="w")

    def _set_mod(self, name, var):
        if name in self.mod_selected:
            self.mod_selected[name] = var.get()

    def _toggle_all_mods(self, master):
        on = master.get()
        for name in self.mod_selected:
            self.mod_selected[name] = on
            v = self.mod_vars.get(name)
            if v is not None:
                v.set(on)

    def _set_other(self, name, var):
        e = self.entry_by_name.get(name)
        if not e:
            return
        e["action"] = "migrate" if var.get() else "ignore"
        self._refresh_tree_row(name)

    def _toggle_all_other(self, master):
        on = master.get()
        for name, v in self.other_vars.items():
            v.set(on)
            self._set_other(name, v)

    def _current_groups(self):
        """勾选状态 → migrate_groups 字典。"""
        mg = {}
        for key, var in self.group_vars.items():
            if key in ("other", "mods"):
                continue
            mg[key] = bool(var.get())
        # other: 只要任一未知条目被勾选迁移,就带上
        if any(e.get("action") == "migrate"
               for e in self.entries
               if (e.get("group") or e.get("category")) == "other"):
            mg["other"] = True
        # mods: 只要任一 mod 勾选迁移,就带上
        if any(self.mod_selected.values()):
            mg["mods"] = True
        return mg

    def _load_defaults(self):
        cfg = self.cfg
        if cfg.get("source_mods_folder"):
            # 兼容旧的 source_mods_folder:默认翻到实例目录
            p = Path(cfg["source_mods_folder"])
            if p.parent.name == "mods":
                p = p.parent.parent
            self.var_instance.set(str(p))
        if cfg.get("target_game_version"):
            self.var_target.set(str(cfg["target_game_version"]))
        if cfg.get("loader"):
            self.var_loader.set(str(cfg["loader"]))
        if cfg.get("out_folder"):
            self.var_out.set(str(Path(cfg["out_folder"])))

    # ------------------------------------------------------------ 浏览
    def _saved_initialdir(self, key):
        """浏览对话框的初始目录:优先用配置里已存路径的父目录。"""
        p = self.cfg.get(key, "")
        try:
            if p and Path(p).parent.is_dir():
                return str(Path(p).parent)
        except Exception:
            pass
        return ""

    def _askdir(self, title, key):
        kw = {"title": title, "parent": self.root}
        d0 = self._saved_initialdir(key)
        if d0:
            kw["initialdir"] = d0
        return filedialog.askdirectory(**kw)

    def _browse_instance(self):
        d = self._askdir("选择旧实例文件夹", "source_mods_folder")
        if d:
            self.var_instance.set(d)

    def _browse_new(self):
        d = self._askdir("选择新实例文件夹(可不存在,会自动创建)",
                         "source_mods_folder")
        if d:
            self.var_new_instance.set(d)

    def _browse_out(self):
        d = self._askdir("选择 mod 输出目录", "out_folder")
        if d:
            self.var_out.set(d)

    # ------------------------------------------------------------ 扫描
    def _do_scan(self):
        folder = self.var_instance.get().strip()
        if not folder:
            messagebox.showwarning("提示", "请先选择旧实例文件夹。")
            return
        if not Path(folder).is_dir():
            messagebox.showerror("错误", f"文件夹不存在:\n{folder}")
            return
        try:
            self.entries = scan.classify_instance(folder)
        except Exception as e:
            messagebox.showerror("错误", f"扫描失败:{e}")
            return
        self._fill_tree()
        self._rebuild_groups()
        self.nb.select(1)      # 跳到第 2 页
        other = [e for e in self.entries
                 if (e.get("group") or e.get("category")) == "other"]
        if other:
            self.log_put(f"[扫描] 有 {len(other)} 个无法识别的条目,"
                         "已列入『其他文件夹』(第 3 页),默认不迁移,可逐个勾选。")
        self.log_put(f"[扫描] 已列出 {len(self.mod_selected)} 个 mod(第 3 页),"
                     "默认全部迁移,可逐个取消不想带的。")

    def _fill_tree(self):
        self.tree.delete(*self.tree.get_children())
        self.tree_items = {}
        self.entry_by_name = {e["name"]: e for e in self.entries}
        for e in self.entries:
            grp = e.get("group") or e.get("category")
            iid = self.tree.insert("", "end",
                                   values=(e["name"],
                                           scan.GROUP_LABEL.get(grp, grp),
                                           e["category_label"],
                                           ACTION_LABEL.get(e["action"],
                                                            e["action"])))
            self.tree_items[e["name"]] = iid

    def _refresh_tree_row(self, name):
        """刷新某行的"处理"列(用于『其他文件夹』逐项勾选后同步)。"""
        e = self.entry_by_name.get(name)
        iid = self.tree_items.get(name)
        if not e or not iid:
            return
        grp = e.get("group") or e.get("category")
        self.tree.item(iid, values=(e["name"], scan.GROUP_LABEL.get(grp, grp),
                                    e["category_label"],
                                    ACTION_LABEL.get(e["action"], e["action"])))

    def _toggle_action(self, _event):
        sel = self.tree.selection()
        if not sel:
            return
        idx = self.tree.index(sel[0])
        e = self.entries[idx]
        cur = e["action"]
        if cur == "mods":
            return
        if cur == "ask":
            ok = messagebox.askyesno(
                "无法识别的条目",
                f"条目「{e['name']}」无法自动识别是什么。\n\n"
                "选「是」= 一并迁移到新实例;\n选「否」= 忽略它。")
            e["action"] = "migrate" if ok else "ignore"
        elif cur == "migrate":
            e["action"] = "ignore"
        else:
            e["action"] = "migrate"
        self.tree.item(sel[0], values=(e["name"],
                                       scan.GROUP_LABEL.get(e["group"] or e["category"],
                                                            e["group"] or e["category"]),
                                       e["category_label"],
                                       ACTION_LABEL[e["action"]]))

    # ------------------------------------------------------------ 运行
    def _build_opts(self):
        return engine.Options(
            use_modrinth=self.var_mr.get(),
            use_github=self.var_gh.get(),
            migrate_groups=self._current_groups(),
            update_resourcepacks=self.var_up_rp.get(),
            update_shaderpacks=self.var_up_sp.get(),
            keep_tag_prefix=self.cfg.get("keep_tag_prefix", True),
            prefer_stable=self.cfg.get("prefer_stable", True),
        )

    def _confirm_unknowns(self):
        """把仍未决定的未知条目问一遍。返回 False 表示用户取消。"""
        unresolved = [e for e in self.entries if e["action"] == "ask"]
        if not unresolved:
            return True
        names = "\n".join("  • " + e["name"] for e in unresolved[:20])
        more = f"\n  …共 {len(unresolved)} 项" if len(unresolved) > 20 else ""
        ok = messagebox.askyesno(
            "无法识别的条目",
            f"这些条目无法自动识别是什么:\n{names}{more}\n\n"
            "选「是」= 一并迁移到新实例;\n选「否」= 忽略它们。")
        act = "migrate" if ok else "ignore"
        for e in unresolved:
            e["action"] = act
        self._fill_tree()
        return True

    def _on_start(self):
        if self.running:
            return
        folder = self.var_instance.get().strip()
        target = self.var_target.get().strip()
        if not folder or not target:
            messagebox.showwarning("提示", "请填写旧实例文件夹和目标 MC 版本。")
            return
        if not self._confirm_unknowns():
            return

        opts = self._build_opts()
        new_instance = self.var_new_instance.get().strip() or None
        out = str(Path(self.var_out.get().strip()
                       or config.APP_DIR / "output" / f"mods-{target}"))
        self.var_out.set(out)

        self.cfg.update({"source_mods_folder": folder,
                         "target_game_version": target,
                         "loader": self.var_loader.get(),
                         "out_folder": out,
                         "use_github": self.var_gh.get(),
                         "update_resourcepacks": self.var_up_rp.get(),
                         "update_shaderpacks": self.var_up_sp.get()})
        config.save_config(self.cfg)

        self.running = True
        util.reset_cancel()
        self.btn_start.config(state="disabled")
        self.btn_cancel.config(state="normal")
        self.lbl_status.config(text="运行中…")
        self.log_put(f"== 开始: {folder} → MC {target} ==")
        args = dict(source_instance=folder, new_instance=new_instance,
                    target=target, loader=self.var_loader.get(),
                    out=out, cfg=self.cfg, opts=opts, entries=self.entries,
                    dry_run=self.var_dryrun.get(),
                    mod_selected=dict(self.mod_selected))
        threading.Thread(target=self._worker, args=(args,), daemon=True).start()

    def _worker(self, args):
        try:
            result = engine.run(**args)
            self.q.put(("__done__", result))
        except Exception as e:
            import traceback
            self.q.put(("__error__", f"{e}\n{traceback.format_exc()}"))

    def _drain(self):
        try:
            while True:
                item = self.q.get_nowait()
                if isinstance(item, str):
                    self.log_put(item)          # worker 塞进来的纯日志
                else:
                    kind, payload = item
                    if kind == "__done__":
                        self._on_done(payload)
                    elif kind == "__error__":
                        self._on_error(payload)
                    else:
                        self.log_put(payload)
        except queue.Empty:
            pass
        except Exception:
            # 处理单条消息出错不能拖死整个日志循环
            import traceback
            traceback.print_exc()
        self.root.after(120, self._drain)

    # ------------------------------------------------------------ 日志/结果
    def log_put(self, msg):
        self.log.config(state="normal")
        self.log.insert("end", str(msg) + "\n")
        self.log.see("end")
        self.log.config(state="disabled")

    def _on_cancel(self):
        if not self.running:
            return
        util.cancel()
        self.btn_cancel.config(state="disabled")
        self.lbl_status.config(text="正在取消…")
        self.log_put("⏹ 正在取消,等当前下载/请求中断后退出 …")

    def _on_done(self, result):
        self.running = False
        self.btn_start.config(state="normal")
        self.btn_cancel.config(state="disabled")
        cancelled = (result.get("meta") or {}).get("cancelled")
        self.lbl_status.config(text="已取消" if cancelled else "完成")
        if cancelled:
            self.log_put("✋ 已取消:仅完成部分下载,报告仍已生成(内容为已完成部分)。")
        self.last_report = result["report"]
        self.btn_open.config(state="normal")
        self.btn_report.config(state="normal")
        r = result.get("results", [])
        ok = sum(1 for x in r if x["status"] == "ok")
        nov = sum(1 for x in r if x["status"] == "no_version")
        nf = sum(1 for x in r if x["status"] == "not_found")
        dlf = sum(1 for x in r if x["status"] == "download_failed")
        self.log_put("=" * 46)
        self.log_put(f"✅ 已就绪 {ok} | ⚠️ 无版本 {nov} | ❌ 需手动 {nf} | 💥 失败 {dlf}")
        mig = result.get("migration")
        if mig:
            self.log_put(f"📦 迁移: 复制 {mig['copied']} 项,跳过 {mig['skipped']} 项")
        self.log_put(f"📄 报告: {result['report']}")
        self.log_put("   (每个 mod 的具体结果已弹出窗口,关掉即可)")
        self._show_result_window(result)

    # ------------------------------------------------------------ 结果窗口
    def _result_summary_text(self, result):
        """把升级结果组织成分类清单(供结果窗口展示,只列结果不啰嗦)。"""
        r = result.get("results", [])
        meta = result.get("meta", {})
        target = meta.get("target", "")
        L = [f"本次目标:把 mod 升到 MC {target} 版", ""]

        # GitHub 自动匹配的单独归到 🤖 栏,不混进"已更新"
        ok = [x for x in r if x["status"] == "ok"
              and not str(x.get("slug", "")).startswith("github:")]
        nov = [x for x in r if x["status"] == "no_version"]
        nf = [x for x in r if x["status"] == "not_found"]
        dlf = [x for x in r if x["status"] == "download_failed"]

        if not r:
            L.append("没有需要处理的 mod。")

        if ok:
            L.append(f"✅ 已更新 / 已就绪({len(ok)})")
            for x in ok:
                name = (x.get("tag", "") + x.get("title", "")).strip() \
                    or x.get("old_file", "")
                if x.get("note") == "源 mod 已是目标版本,本地复用":
                    L.append(f"  • {name}(本地已是最新版本)")
                else:
                    ver = x.get("new_version", "")
                    L.append(f"  • {name} → 新版 {ver}" if ver else f"  • {name}")
            L.append("")

        if nov:
            L.append(f"⚠️ 没有 MC {target} 的版本({len(nov)})")
            for x in nov:
                name = (x.get("tag", "") + x.get("title", "")).strip() \
                    or x.get("old_file", "")
                L.append(f"  • {name}——{x.get('note', '')}")
            L.append("")

        if nf:
            L.append(f"❌ 自动找不到新版({len(nf)})")
            for x in nf:
                name = x.get("title", "") or x.get("old_file", "")
                L.append(f"  • {name}——{x.get('note', '')}")
            L.append("")

        if dlf:
            L.append(f"💥 下载失败({len(dlf)})")
            for x in dlf:
                name = (x.get("tag", "") + x.get("title", "")).strip() \
                    or x.get("old_file", "")
                L.append(f"  • {name}——{x.get('note', '')}")
            L.append("")

        mig = result.get("migration")
        if mig:
            L.append(f"📦 已迁移到新实例 —— 复制 {mig.get('copied', 0)} 项,"
                     f"跳过 {mig.get('skipped', 0)} 项")
            m_mods = mig.get("mods") or []
            others = [n for n in (mig.get("migrated") or []) if n not in m_mods]
            if m_mods:
                L.append(f"  • 模组({len(m_mods)}):" + "、".join(m_mods))
            if others:
                L.append(f"  • 文件夹/配置({len(others)}):" + "、".join(others))
            sm = mig.get("skipped_mods") or []
            if sm:
                L.append("")
                L.append(f"⏭ 没迁到新实例的 mod({len(sm)})")
                L.append("  • " + "、".join(sm))
            L.append("")

        gp = meta.get("github_pending", [])
        if gp:
            L.append(f"🤖 GitHub 按名字自动匹配({len(gp)})")
            for g in gp:
                L.append(f"  • {g['old']} ← 仓库 {g['repo']}")
            L.append("")

        dis = meta.get("disabled", [])
        if dis:
            L.append(f"🔒 忽略的({len(dis)})")
            L.append("  • " + "、".join(dis))
            L.append("")

        pu = meta.get("pack_updates", {})
        for grp, val in pu.items():
            label = "资源包" if grp == "resourcepacks" else "光影"
            m = val.get("meta", {})
            if val.get("results"):
                L.append(f"🎨 {label}:更新 {m.get('updated', 0)} 个,"
                         f"没找到新版 {len(m.get('not_found', []))} 个")
                for x in val.get("results", []):
                    if x.get("status") == "ok":
                        L.append(f"  • {x.get('old_file', '')} → "
                                 f"{x.get('new_file', '')}")
                L.append("")

        return "\n".join(L)

    def _show_result_window(self, result):
        """升级完成后弹出一个小白友好结果窗口(不阻塞,可关掉)。"""
        text = self._result_summary_text(result)
        if self.var_dryrun.get():
            text = "【演练模式:只是预览,不会真的下载/迁移】\n\n" + text
        win = tk.Toplevel(self.root)
        win.title("升级结果")
        win.geometry("680x560")
        win.transient(self.root)
        frame = ttk.Frame(win)
        frame.pack(fill="both", expand=True, padx=10, pady=(10, 4))
        t = tk.Text(frame, wrap="word", font=("Microsoft YaHei UI", 10),
                    padx=12, pady=8)
        vs = ttk.Scrollbar(frame, orient="vertical", command=t.yview)
        t.configure(yscrollcommand=vs.set)
        t.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        t.insert("1.0", text)
        t.config(state="disabled")
        ttk.Button(win, text="知道了", command=win.destroy).pack(pady=(0, 10))

    def _on_error(self, err):
        self.running = False
        self.btn_start.config(state="normal")
        self.btn_cancel.config(state="disabled")
        self.lbl_status.config(text="出错")
        self.log_put("[错误]\n" + str(err))
        messagebox.showerror("出错了", str(err)[:500])

    def _open_out(self):
        out = self.var_out.get().strip()
        if not out:
            return
        out = os.path.normpath(out)
        if not os.path.isdir(out):
            parent = os.path.dirname(out)
            if parent and os.path.isdir(parent):
                out = parent
            else:
                messagebox.showinfo("提示", "输出目录还不存在:\n" + out)
                return
        os.startfile(out)

    def _open_report(self):
        if self.last_report:
            subprocess.Popen(["notepad", str(self.last_report)])


def main():
    util.utf8_console()
    root = tk.Tk()
    PanelApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
