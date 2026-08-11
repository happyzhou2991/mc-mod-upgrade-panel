# MC Mod Upgrade Panel (1.1.0)

Upgrade a Minecraft instance to a new version in one click (e.g. 26.1 → 26.2). Each mod is identified automatically and pulled from Modrinth at the target version; mods not found there fall back to a GitHub search by name (results need manual confirmation). User data — config, saves, resource packs, shader packs, etc. — can be migrated to the new instance by checking export groups.

Ships as a single exe for others to use; no Python installation required.

## Features

- **Automatic mod upgrade**: identifies mods on Modrinth by file hash and downloads the jar for the target MC version; mods not found go through a GitHub auto-search (results flagged for manual review)
- **Per-mod selection**: on tab 3, tick which mods to migrate to the new instance and which to leave behind (all ticked by default). Ticked mods are updated and copied into the new instance's `mods` folder; unticked ones are neither updated nor copied
- **Export groups** ticked per group at migration: game settings, personal data, drawn maps, JEI/EMI data, resource/texture packs, shader packs, screenshots, exported structures, replay recordings, single-player saves, server list, mod configs, mod data directories
- **Resource/shader packs** have their own "update or not" section: zip packs are checked against Modrinth for a newer version; folder-style packs are migrated only (never updated)
- **Unknown entries** end up in an "Other folders" group where you tick each one to migrate
- **Dry-run mode**: previews results without downloading or migrating
- **Plain-language result window**: after the run a pop-up window lists per category which mods were updated, which have no target version, which were not found, which failed to download, and which were migrated — no need to read the log
- **Fresh green UI theme**: a clean light-gray + grass-green look across tabs, cards, buttons and step banners
- **Live download progress + Cancel**: slow downloads log MB/% every few seconds so the panel never looks frozen, and a **Cancel** button on the log page stops the run cleanly (a partial report is still written)
- **Version-query caching**: target-version lookups are cached for 12 hours, so a rerun skips the network when files are already downloaded (no redundant timeouts on slow networks)
- **Source already at target version**: if the old mod is already the newest for the target version, it is copied locally to the output folder instead of downloaded again
- **No stale-mod migration**: mods that could not be updated to the target version are NOT copied into the new instance (an old-version mod would not run) — they are listed as skipped in the log and report
- **Mouse-wheel scrolling**: the long mod-selection list on tab 3 scrolls with the mouse wheel anywhere over it, not just by dragging the scrollbar
- **Updated packs go to the right place**: updated resource/shader pack zips go directly into the new instance's `resourcepacks` / `shaderpacks` (created there if missing, never inside the mods folder)
- **GitHub mirror fallback**: if a GitHub download fails directly, it automatically retries through the configurable `github_mirrors` list
- Each panel page shows a step banner so first-time users know what to do

## Run

```powershell
python panel.py
python mc_mod_upgrader.py upgrade --source <mods-folder> --game-version 26.2 --loader fabric
```

## Using the GUI panel

Run `panel.py` or `dist\MCModUpgradePanel.exe`.

Four tabs:

| Tab | What it does |
|---|---|
| 1. Settings | Pick the old instance folder, target MC version, loader; optional "dry-run" mode. Step banner on top |
| 2. Scan & Migrate | Scans the instance and lists every entry with its category; double-click a row to toggle Migrate / Ignore |
| 3. Update Options | Tick mod update sources; a dedicated section for "update resource/shader packs or not"; tick each mod to migrate; tick export groups; fill in the new instance folder and mod output folder |
| 4. Log & Results | Click "Start upgrade", watch the live log (downloads show progress; Cancel stops the run), then open the output folder / report |

Flow: pick instance → scan → tick migrate items (including per-mod selection) → start → read `report.md`.
Ticked mods are copied into the new instance's `mods` folder automatically (updated version when available, otherwise the original jar).

Dry-run mode: no download, no migration, preview only.

## Using the CLI

```powershell
python mc_mod_upgrader.py upgrade --source "<old-instance>/mods" --game-version 26.2 --dry-run
python mc_mod_upgrader.py migrate --old <old-instance> --new <new-instance>
```

## Build the exe

```powershell
powershell -ExecutionPolicy Bypass -File build_exe.ps1
```

Output: `dist\MCModUpgradePanel.exe`, ~12 MB, single file, no Python needed. Config, cache, and the output folder are created next to the exe.

## Report (report.md)

- ✅ Updated / ready: bumped to the target version, verified for 26.2
- 🤖 GitHub auto-match: downloaded by name search — confirm these before launching
- ⚠️ No target version: Modrinth supports only up to some version
- ❌ Manual needed: not found on Modrinth or GitHub
- 📦 Export groups: what each group exported and whether it was ticked
- 🎨 Resource/shader packs: migrated; if "update" was ticked, lists updated / not-found / folder-style-only-migrated
- 📦 Migration results: copied/skipped counts per group; the "Mods" row lists the mods copied into the new instance
- 🔒 Disabled / excluded mods: mods unticked on tab 3 (neither updated nor migrated)

## Config file `mods_config.json`

Auto-generated next to the exe or script; editable by hand:

| Key | Meaning |
|---|---|
| `source_mods_folder` | Source instance's mods folder |
| `target_game_version` | Target MC version, e.g. 26.2 |
| `loader` | Loader, e.g. fabric |
| `use_github` | Enable GitHub auto-search |
| `update_resourcepacks` | Try Modrinth update for resource packs |
| `update_shaderpacks` | Try Modrinth update for shader packs |
| `github_token` | GitHub personal access token (raises API rate limits) |
| `keep_tag_prefix` | Keep the `[中文名] ` prefix in file names |
| `prefer_stable` | Prefer release versions |
| `excluded` | File names to skip, exact match |
| `manual_overrides` | Manual download source, `{"file.jar": {"url": "...", "filename": "save-as.jar", "sha1": "optional"}}` |
| `api_timeout` | Timeout (seconds) for API/JSON requests, default 30 |
| `download_timeout` | Read timeout (seconds) while downloading a file, default 60 |
| `download_retries` | Retry count after a failed download (total attempts = retries + 1) |
| `http_proxy` / `https_proxy` | Proxy for all requests, e.g. `http://127.0.0.1:7890`. Leave empty to use the system/environment proxy |
| `github_mirrors` | List of GitHub download mirror prefixes tried after direct access fails (empty list = direct only) |

## Files

| File | Purpose |
|---|---|
| `panel.py` | GUI panel, main entry |
| `mc_mod_upgrader.py` | CLI entry |
| `mcupgrade/` | Engine package, shared by CLI and GUI |
| `build_exe.ps1` | Packaging script |
| `dist/` | Built exe |
| `mods_config.json` / `mods_manifest.json` | Config / identification & search cache |

## Notes

- Requires network access to `api.modrinth.com`, `api.github.com`, and `github.com`
- If downloads keep failing on a slow/blocked network (timeouts, `WinError 10054`), raise `download_retries` / `download_timeout` in `mods_config.json`, or set `http_proxy`/`https_proxy` when a proxy is required
- The tool only handles mods; the game itself and the loader are handled by your launcher
- GitHub matching is heuristic — double-check items flagged "confirm manually" before starting the game
- Migration only copies; it never overwrites or deletes
- Needs Windows 10/11; no Python or .NET required; an existing MC instance folder is used as the source
- The unsigned exe may be flagged by antivirus — allow it if that happens
