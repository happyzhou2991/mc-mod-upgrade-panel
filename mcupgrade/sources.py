# -*- coding: utf-8 -*-
"""模组来源:Modrinth(识别/查版本/下载)与 GitHub(按名字搜索/抓 release/匹配)。

GitHub 策略:
  - 搜索仓库用 Search API(未登录 10 次/分钟,够用)
  - 抓 release 资产优先抓网页版 releases 页(无 API 限流问题)
  - 配置里填了 github_token 则用 API(限流高很多)
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request

from . import util

MODRINTH_API = "https://api.modrinth.com/v2"
GITHUB_API = "https://api.github.com"
GITHUB_DL = "https://github.com"


# ---------------------------------------------------------------- Modrinth
def identify_mod(manifest, jar_path):
    """按文件哈希识别 jar 对应的 Modrinth 项目。返回 dict 或 None。"""
    fname = jar_path.name
    by_filename = manifest.setdefault("by_filename", {})
    if fname in by_filename:
        return {"project_id": by_filename[fname]["project_id"]}

    sha1 = util.sha1_of_file(jar_path)
    resp = util.http_json(f"{MODRINTH_API}/version_file/{sha1}")
    if not resp or not resp.get("project_id"):
        return None

    pid = resp["project_id"]
    by_filename[fname] = {"project_id": pid,
                          "version_number": resp.get("version_number", "")}

    projects = manifest.setdefault("projects", {})
    if pid not in projects:
        proj = util.http_json(f"{MODRINTH_API}/project/{pid}")
        if proj:
            projects[pid] = {"slug": proj.get("slug", ""),
                             "title": proj.get("title", "")}
        else:
            projects[pid] = {"slug": "", "title": pid}
    return {"project_id": pid}


def query_target_version(project_id, target_version, loader):
    """查指定 MC 版本 + 加载器下的版本列表,按发布日期降序。
    loader 传 None 时只按 MC 版本过滤(资源包/光影没有 loader 标签)。"""
    params = {"game_versions": json.dumps([target_version])}
    if loader:
        params["loaders"] = json.dumps([loader])
    url = f"{MODRINTH_API}/project/{project_id}/version?" + urllib.parse.urlencode(params)
    data = util.http_json(url)
    if not data:
        return []
    return sorted(data, key=lambda v: v.get("date_published") or "", reverse=True)


def query_latest_supported(project_id, loader):
    """查该 mod 最近版本中最高支持到哪个 MC 版本(用于"无目标版本"的说明)。"""
    params = {"loaders": json.dumps([loader]), "limit": 20}
    url = f"{MODRINTH_API}/project/{project_id}/version?" + urllib.parse.urlencode(params)
    data = util.http_json(url)
    if not data:
        return None
    best = None
    for v in data:
        for gv in (v.get("game_versions") or []):
            if best is None or util._mc_tuple(gv) > util._mc_tuple(best):
                best = gv
    return best


def pick_main_file(version):
    """从版本里挑主文件(.jar 且非 -sources)。"""
    files = version.get("files") or []
    if not files:
        return None
    for f in files:
        if f.get("primary"):
            return f
    for f in files:
        fn = f.get("filename", "")
        if fn.lower().endswith(".jar") and "sources" not in fn.lower():
            return f
    return files[0]


# ---------------------------------------------------------------- GitHub
def _auth(token):
    return {"Authorization": f"Bearer {token}"} if token else {}


def _search_repos(query, limit=5, token=""):
    """GitHub 搜索仓库。返回 [{full_name, stars, html_url}];失败(限流/网络)返回 None。"""
    q = urllib.parse.quote(query)
    url = (f"{GITHUB_API}/search/repositories?q={q}&sort=stars"
           f"&order=desc&per_page={limit}")
    data = util.http_json(url, headers=_auth(token))
    if data is None:
        return None
    if not data.get("items"):
        return []
    return [{"full_name": it.get("full_name", ""),
             "stars": it.get("stargazers_count", 0),
             "html_url": it.get("html_url", "")}
            for it in data["items"]]


def _releases_api(full_name, per_page=10, token=""):
    """GitHub API 拉 releases 资产。失败/限流返回 None。"""
    url = f"{GITHUB_API}/repos/{full_name}/releases?per_page={per_page}"
    data = util.http_json(url, headers=_auth(token))
    if not data:
        return None
    items = []
    for r in data:
        tag = r.get("tag_name", "")
        for a in (r.get("assets") or []):
            items.append({"tag": tag, "filename": a.get("name", ""),
                          "download_url": a.get("browser_download_url", "")})
    return items


def _releases_html(full_name, limit=30):
    """从 GitHub releases 网页抓 (tag, filename),绕开 API 限流。"""
    url = f"{GITHUB_DL}/{full_name}/releases"
    req = urllib.request.Request(url, headers={"User-Agent": util.USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8", "replace")
    except Exception as e:
        util.emit(f"  [GitHub] 页面抓取失败 {full_name}: {e}")
        return None
    pairs = re.findall(r"/releases/download/([^\"']+/[^\"']+)", html)
    seen, items = set(), []
    for tag_enc, asset_enc in (p.split("/", 1) for p in pairs):
        k = (tag_enc, asset_enc)
        if k in seen:
            continue
        seen.add(k)
        items.append({"tag": urllib.parse.unquote(tag_enc),
                      "filename": urllib.parse.unquote(asset_enc),
                      "download_url": (f"{GITHUB_DL}/{full_name}/releases/"
                                       f"download/{tag_enc}/{asset_enc}")})
        if len(items) >= limit:
            break
    return items


def _get_release_items(full_name, token=""):
    if token:
        api = _releases_api(full_name, token=token)
        if api:
            return api
    return _releases_html(full_name)


def _score_match(tag, filename, target, loader):
    """给 (tag, filename) 打分,匹配目标 MC 版本和加载器的程度。"""
    t = str(target).lower()
    low = filename.lower()
    s = 0
    if t in low:
        s += 10
    elif t.replace(".", "") in low.replace(".", ""):
        s += 8
    if loader in low:
        s += 4
    if low.endswith(".jar") and "sources" not in low:
        s += 1
    if t in str(tag).lower():
        s += 3
    return s


def github_resolve(manifest, mod_name, mod_id, target_version, loader,
                   token="", max_repos=5):
    """按 mod 名在 GitHub 上找匹配 release。返回 dict。

    结果缓存进 manifest["github"]。返回 {ok, repo, tag, url, filename,
    candidates, note}。匹配是启发式,调用方应提示用户人工确认。
    mod_name 优先,搜不到再试 mod_id(短 id 如 ommc 单独搜命中率低)。"""
    cache = manifest.setdefault("github", {})
    key = (mod_name or mod_id or "").strip()
    if key in cache:
        c = dict(cache[key])
        c["cached"] = True
        return c

    repos = None
    tried = []
    for q in filter(None, dict.fromkeys([mod_name, mod_id])):
        util.emit(f"  [GitHub] 按名字搜索: {q}")
        repos = _search_repos(q, token=token)
        tried.append(q)
        time.sleep(1)
        if repos is not None and repos:
            break
    if repos is None:
        # 限流/网络失败:不缓存,下次运行会重试
        return {"ok": False, "note": "GitHub 搜索失败(可能限流),本次跳过",
                "candidates": [], "cached": False}
    if not repos:
        entry = {"ok": False, "note": "GitHub 上没搜到仓库",
                 "candidates": [], "cached": False}
        cache[key] = entry
        return entry

    candidates, best = [], None
    for repo in repos[:max_repos]:
        items = _get_release_items(repo["full_name"], token)
        if not items:
            continue
        for it in items:
            score = _score_match(it["tag"], it["filename"], target_version, loader)
            if score <= 0:
                continue
            candidates.append({"repo": repo["full_name"], "tag": it["tag"],
                               "filename": it["filename"], "score": score})
            if score >= 10:          # 至少匹配到目标 MC 版本
                cand = {"repo": repo["full_name"], "tag": it["tag"],
                        "url": it["download_url"], "filename": it["filename"],
                        "score": score}
                if best is None or score > best["score"]:
                    best = cand

    # 候选去重(按 仓库+tag+文件名)
    seen_c = set()
    uniq = []
    for c in candidates:
        k = (c["repo"], c["tag"], c["filename"])
        if k in seen_c:
            continue
        seen_c.add(k)
        uniq.append(c)
    candidates = uniq
    candidates.sort(key=lambda c: -c["score"])
    if best:
        entry = {"ok": True, "repo": best["repo"], "tag": best["tag"],
                 "url": best["url"], "filename": best["filename"],
                 "candidates": candidates[:5],
                 "note": "GitHub 自动匹配,请人工确认", "cached": False}
    else:
        entry = {"ok": False,
                 "note": "GitHub 上没找到匹配目标版本的 release",
                 "candidates": candidates[:5], "cached": False}
    cache[key] = entry
    return entry
