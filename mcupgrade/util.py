# -*- coding: utf-8 -*-
"""基础工具:HTTP 请求、哈希、文件名、版本判断、fabric.mod.json 解析、消息输出。"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

USER_AGENT = "mcupgrade/0.1-beta (local MC mod upgrade tool)"
SLEEP = 0.15            # 请求间延时,礼貌限速

# 网络参数:默认值,可用 configure_network(cfg) 按配置覆盖
API_TIMEOUT = 30         # API/JSON 请求超时(秒)
DOWNLOAD_TIMEOUT = 60    # 下载单次读取超时(秒)
DOWNLOAD_RETRIES = 2     # 下载失败后的重试次数(总尝试 = 重试 + 1)

# 全局取消标志:GUI 点"取消"时置位,网络循环据此尽快收尾
_cancel = threading.Event()


def configure_network(cfg):
    """从配置读取网络参数覆盖默认值(api_timeout/download_timeout/download_retries)。"""
    global API_TIMEOUT, DOWNLOAD_TIMEOUT, DOWNLOAD_RETRIES
    try:
        if cfg.get("api_timeout"):
            API_TIMEOUT = int(cfg["api_timeout"])
        if cfg.get("download_timeout"):
            DOWNLOAD_TIMEOUT = int(cfg["download_timeout"])
        if cfg.get("download_retries") is not None:
            DOWNLOAD_RETRIES = int(cfg["download_retries"])
    except (TypeError, ValueError):
        pass


def cancel():
    """请求取消(可跨线程调用)。"""
    _cancel.set()


def reset_cancel():
    """开始新一轮运行前清除取消标志。"""
    _cancel.clear()


def cancelled():
    """是否已请求取消。"""
    return _cancel.is_set()

TAG_RE = re.compile(r"^(\[[^\[\]]*\]\s*)")        # 匹配并捕获 [中文名] 前缀
INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# 消息输出:默认 print;CLI/GUI 可注入自己的处理函数
_message_handler = None


def set_message_handler(fn):
    """注入消息处理函数(CLI 用 print,GUI 用 queue)。"""
    global _message_handler
    _message_handler = fn


def emit(msg=""):
    if _message_handler:
        _message_handler(str(msg))
    else:
        print(str(msg))


def utf8_console():
    """让中文/emoji 在控制台正常输出(尽力而为)。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def http_json(url, retries=4, headers=None, timeout=None):
    """GET 请求返回 JSON;404/410 或最终失败返回 None。带 429 退避重试。"""
    if timeout is None:
        timeout = API_TIMEOUT
    req_headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        req_headers.update(headers)
    for attempt in range(retries):
        if cancelled():
            emit("  [已取消]")
            return None
        req = urllib.request.Request(url, headers=req_headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 1 + attempt * 3
                emit(f"  [限流] 稍候 {wait}s 后重试 ...")
                time.sleep(wait)
                continue
            if e.code in (404, 410):
                return None
            emit(f"  [HTTP {e.code}] {url}")
            time.sleep(1 + attempt)
        except (urllib.error.URLError, TimeoutError) as e:
            emit(f"  [网络错误] {e}")
            time.sleep(1 + attempt)
    return None


def download_file(url, dest, expect_sha1=None, retries=None):
    """下载文件到 dest,可校验 SHA1。返回 True/False。

    下载中每 ~3 秒报一次进度(便于烂网下确认没卡死);读超时由
    DOWNLOAD_TIMEOUT 控制;收到取消请求(util.cancel())会删掉
    半成品文件并返回 False。
    """
    if retries is None:
        retries = DOWNLOAD_RETRIES
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    attempts = retries + 1
    for attempt in range(attempts):
        if cancelled():
            emit("  [已取消]")
            dest.unlink(missing_ok=True)
            return False
        done = 0
        aborted = False
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT) as resp, \
                    open(dest, "wb") as out:
                try:
                    total = int(resp.headers.get("Content-Length") or 0) or None
                except (TypeError, ValueError):
                    total = None
                last_prog = time.monotonic() - 3     # 让第一条进度 3s 内出现
                while True:
                    if cancelled():
                        emit("  [已取消]")
                        aborted = True
                        break
                    chunk = resp.read(1 << 16)
                    if not chunk:
                        break
                    out.write(chunk)
                    done += len(chunk)
                    now = time.monotonic()
                    if now - last_prog >= 3:
                        last_prog = now
                        emit(_progress_line(dest.name, done, total))
            if aborted:
                dest.unlink(missing_ok=True)
                return False
            if expect_sha1 and sha1_of_file(dest).lower() != expect_sha1.lower():
                emit(f"  [校验失败] {dest.name}:SHA1 不匹配,第 {attempt + 1}/"
                     f"{attempts} 次,重试 ...")
                dest.unlink(missing_ok=True)
                time.sleep(1)
                continue
            emit(f"  ✓ 下载完成 {done / 1e6:.1f} MB")
            return True
        except Exception as e:
            if attempt < retries:
                msg = f"  [下载中断] {dest.name}"
                if done:
                    msg += f":已下 {done / 1e6:.1f} MB"
                msg += f",{e},第 {attempt + 1}/{attempts} 次,重试 ..."
                emit(msg)
            else:
                emit(f"  [下载失败] {dest.name}: {e}")
            dest.unlink(missing_ok=True)
            time.sleep(1 + attempt * 2)
    return False


def _progress_line(name, done, total):
    """下载进度的一行文本;total 为 None(无 Content-Length)时只报已下载量。"""
    if total:
        pct = done * 100 // total
        return f"  ⏳ {name}:已下载 {done / 1e6:.1f}/{total / 1e6:.1f} MB ({pct}%)"
    return f"  ⏳ {name}:已下载 {done / 1e6:.1f} MB"


def sha1_of_file(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def sanitize_filename(name):
    name = INVALID_CHARS.sub("_", name)
    name = name.strip().rstrip(".").strip()
    return name or "mod.jar"


def tag_prefix_of(filename):
    m = TAG_RE.match(filename)
    return m.group(1) if m else ""


def _mc_tuple(s):
    """把 MC 版本号转成可比较的元组,如 '26.1.2' -> (26, 1, 2)。"""
    parts = []
    for seg in re.split(r"[^0-9]", str(s)):
        if seg.isdigit():
            parts.append(int(seg))
    return tuple(parts) or (0,)


def read_fabric_mod_meta(jar_path):
    """读 jar 内 fabric.mod.json,返回 {id, name, version, depends}。"""
    try:
        with zipfile.ZipFile(jar_path) as z:
            if "fabric.mod.json" in z.namelist():
                data = json.loads(z.read("fabric.mod.json").decode("utf-8"))
                return {
                    "id": data.get("id", ""),
                    "name": data.get("name", ""),
                    "version": data.get("version", ""),
                    "depends": data.get("depends") or {},
                }
    except Exception:
        pass
    return None


def read_fabric_depends(jar_path):
    """读 jar 内 fabric.mod.json,返回 (minecraft依赖, fabricloader依赖)。"""
    meta = read_fabric_mod_meta(jar_path)
    if meta:
        return meta["depends"].get("minecraft"), meta["depends"].get("fabricloader")
    return None, None


def mc_dep_includes(dep, target):
    """判断 depends.minecraft 的写法是否包含目标 MC 版本。
    返回 True/False,无法解析或未声明返回 None。"""
    if dep is None:
        return None
    t = _mc_tuple(target)
    if isinstance(dep, (list, tuple)):
        return any(mc_dep_includes(d, target) is True for d in dep)
    s = str(dep).strip()
    if not s:
        return None
    s = re.sub(r"^~", "", s)      # Fabric 的 "~26.2" 表示兼容 26.2+
    s = re.sub(r"-$", "", s)      # 尾部 "-" 表示 26.2- 及更高
    s = re.sub(r"^=", "", s)      # "=26.2" 表示精确版本
    if s.endswith(".x"):          # 26.2.x 通配:目标以 26.2 开头即满足
        prefix = s[:-2]
        if re.fullmatch(r"[0-9.]+", prefix):
            p = _mc_tuple(prefix)
            return t[:len(p)] == p
    if re.match(r"[0-9.]", s) and re.fullmatch(r"[0-9.]+", s) is None:
        # 版本串带后缀(如 26.2-beta.4):按">= 前导版本"理解
        m = re.match(r"[0-9.]+", s)
        return t >= _mc_tuple(m.group(0))
    conds = re.findall(r"([<>]=?)\s*([0-9.]+)", s)
    if conds:
        ok = True
        for op, ver in conds:
            tv = _mc_tuple(ver)
            if op == ">=":
                ok = ok and t >= tv
            elif op == "<=":
                ok = ok and t <= tv
            elif op == ">":
                ok = ok and t > tv
            elif op == "<":
                ok = ok and t < tv
        return ok
    if re.fullmatch(r"[0-9.]+", s):
        return _mc_tuple(s) == t
    return None
