"""Obsidian ulanishi: vault'ga `.obsidian/` boshlang'ich sozlamasi va ilovada ro'yxatdan o'tkazish.

Qoidalar:
  - `.obsidian/` ichidagi fayl FAQAT yo'q bo'lsa yoziladi. Egasi Obsidian'da nimanidir
    o'zgartirsa, yig'uvchi unga hech qachon tegmaydi.
  - `.obsidian/` git'ga tushmaydi (brain-push.sh uni .git/info/exclude'ga qo'yadi).
  - Ro'yxatdan o'tkazish `obsidian://open?path=...` URI orqali: Obsidian vault'ni o'zi
    qo'shadi va ochadi (obsidian.json qo'lda tahrirlanmaydi — ilova ochiq bo'lsa buziladi).
"""
from __future__ import annotations

import json
import os
import secrets
import subprocess
import time
import urllib.parse
from pathlib import Path

from . import asos

_CORE = {
    "file-explorer": True, "global-search": True, "switcher": True, "graph": True,
    "backlink": True, "canvas": True, "outgoing-link": True, "tag-pane": True,
    "footnotes": False, "properties": True, "page-preview": True, "daily-notes": True,
    "templates": True, "note-composer": True, "command-palette": True, "slash-command": False,
    "editor-status": True, "bookmarks": True, "markdown-importer": False, "zk-prefixer": False,
    "random-note": False, "outline": True, "word-count": True, "slides": False,
    "audio-recorder": False, "workspaces": False, "file-recovery": True, "publish": False,
    "sync": False, "bases": True, "webviewer": False,
}

_APP = {
    "alwaysUpdateLinks": True,
    "newFileLocation": "folder",
    "newFileFolderPath": "bilim",
    "newLinkFormat": "absolute",
    "useMarkdownLinks": False,
    "attachmentFolderPath": "./ilovalar",
    "defaultViewMode": "preview",
    "readableLineLength": True,
    "showUnsupportedFiles": False,
    # ilovalar/ — xom eksportlar (mijoz yozishmalari) va katta fayllar: git va KB'da ham yo'q
    "userIgnoreFilters": ["/(^|\\/)ilovalar\\//"],
}

_DAILY = {"folder": "kunlik", "format": "YYYY-MM-DD", "template": "", "autorun": False}


def _rang(hex_: str) -> dict:
    return {"a": 1, "rgb": int(hex_.lstrip("#"), 16)}


_GRAPH = {
    "collapse-filter": True, "search": "", "showTags": False, "showAttachments": False,
    "hideUnresolved": True, "showOrphans": True, "collapse-color-groups": False,
    "colorGroups": [
        {"query": "path:kunlik", "color": _rang("#4f8ff7")},
        {"query": "path:bilim", "color": _rang("#2fb36b")},
        {"query": "path:claude", "color": _rang("#9b6bff")},
        {"query": "path:kod", "color": _rang("#f59e0b")},
        {"query": "path:wall-e OR path:abba-sheets-agent", "color": _rang("#ef4444")},
        {"query": "path:tizim OR file:BOSH-SAHIFA OR file:INDEX", "color": _rang("#94a3b8")},
        {"query": "path:chat", "color": _rang("#64748b")},
    ],
    "collapse-display": True, "showArrow": False, "textFadeMultiplier": 0,
    "nodeSizeMultiplier": 1, "lineSizeMultiplier": 1, "collapse-forces": True,
    "centerStrength": 0.52, "repelStrength": 10, "linkStrength": 1, "linkDistance": 250,
}


def _bookmarks() -> dict:
    t = 1764000000000

    def f(path, title):
        return {"type": "file", "ctime": t, "path": path, "title": title}
    return {"items": [
        f("BOSH-SAHIFA.md", "🧠 Bosh sahifa"),
        f("INDEX.md", "📌 INDEX"),
        f("claude/INDEX.md", "💬 Claude ishlari"),
        f("wall-e/INDEX.md", "🤖 WALL-E"),
        f("kod/INDEX.md", "💻 Kod"),
        f("claude/skillar/INDEX.md", "🧩 Skillar"),
        f("tizim/loyihalar.md", "🎯 Loyihalar va xulosalar"),
        f("abba-sheets-agent/holat.md", "WALL-E — joriy holat"),
    ]}


def _workspace() -> dict:
    """Birinchi ochilishda Bosh sahifa o'qish rejimida ochiq turadi."""
    return {
        "main": {"id": "miya-main", "type": "split", "direction": "vertical", "children": [
            {"id": "miya-tabs", "type": "tabs", "children": [
                {"id": "miya-bosh", "type": "leaf", "state": {
                    "type": "markdown", "state": {"file": "BOSH-SAHIFA.md", "mode": "preview", "source": False},
                    "icon": "lucide-file", "title": "BOSH-SAHIFA"}}]}]},
        "left": {"id": "miya-left", "type": "split", "direction": "horizontal", "width": 300, "children": [
            {"id": "miya-left-tabs", "type": "tabs", "children": [
                {"id": "miya-files", "type": "leaf", "state": {"type": "file-explorer", "state": {"sortOrder": "alphabetical"}}},
                {"id": "miya-search", "type": "leaf", "state": {"type": "search", "state": {"query": ""}}},
                {"id": "miya-bm", "type": "leaf", "state": {"type": "bookmarks", "state": {}}}]}]},
        "right": {"id": "miya-right", "type": "split", "direction": "horizontal", "width": 300,
                  "collapsed": True, "children": [
            {"id": "miya-right-tabs", "type": "tabs", "children": [
                {"id": "miya-back", "type": "leaf", "state": {"type": "backlink", "state": {
                    "file": "BOSH-SAHIFA.md", "collapseAll": False, "extraContext": False,
                    "sortOrder": "alphabetical", "showSearch": False, "searchQuery": "",
                    "backlinkCollapsed": False, "unlinkedCollapsed": True}}},
                {"id": "miya-out", "type": "leaf", "state": {"type": "outgoing-link", "state": {
                    "file": "BOSH-SAHIFA.md", "linksCollapsed": False, "unlinkedCollapsed": True}}},
                {"id": "miya-tag", "type": "leaf", "state": {"type": "tag", "state": {
                    "sortOrder": "frequency", "useHierarchy": True}}},
                {"id": "miya-outline", "type": "leaf", "state": {"type": "outline", "state": {
                    "file": "BOSH-SAHIFA.md"}}}]}]},
        "active": "miya-bosh",
        "lastOpenFiles": ["BOSH-SAHIFA.md", "INDEX.md"],
    }


def sozla(vault: Path | None = None, quruq: bool = False) -> list:
    """`.obsidian/` da YO'Q fayllarni yaratadi. Qaytadi: yaratilgan fayllar ro'yxati."""
    v = Path(vault or asos.vault())
    o = v / ".obsidian"
    fayllar = {
        "app.json": _APP, "core-plugins.json": _CORE, "daily-notes.json": _DAILY,
        "graph.json": _GRAPH, "bookmarks.json": _bookmarks(), "appearance.json": {},
    }
    if not (o / "workspace.json").exists():
        fayllar["workspace.json"] = _workspace()
    yaratildi = []
    for nom, d in fayllar.items():
        p = o / nom
        if p.exists():
            continue
        yaratildi.append(nom)
        if not quruq:
            o.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return yaratildi


def _obsidian_json() -> Path:
    return asos.HOME / "Library" / "Application Support" / "obsidian" / "obsidian.json"


def royxatdami(vault: Path | None = None) -> bool:
    v = str(Path(vault or asos.vault()).resolve())
    try:
        d = json.loads(_obsidian_json().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return any(str(Path(x.get("path", "")).resolve()) == v for x in (d.get("vaults") or {}).values())


def ishlayaptimi() -> bool:
    try:
        return subprocess.run(["pgrep", "-x", "Obsidian"], capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def royxatga_qosh(vault: Path | None = None) -> str:
    """Vault'ni Obsidian ro'yxatiga qo'shadi va keyingi ishga tushishda ochiladigan qiladi.
    Obsidian 1.14 da `obsidian://open?path=` ro'yxatda YO'Q vault'ni ochmaydi, shuning uchun
    obsidian.json tahrirlanadi — faqat ilova YOPIQ bo'lganda (ochiq bo'lsa u faylni qayta
    yozib yuboradi). Avval zaxira nusxa: obsidian.json.miya-zaxira.
    Qaytadi: 'bor' | 'qoshildi' | 'ilova-ochiq' | 'xato'."""
    v = str(Path(vault or asos.vault()).resolve())
    if royxatdami(v):
        return "bor"
    if ishlayaptimi():
        return "ilova-ochiq"
    p = _obsidian_json()
    try:
        matn = p.read_text(encoding="utf-8") if p.exists() else '{"vaults":{}}'
        d = json.loads(matn)
        if not isinstance(d.get("vaults"), dict):
            d["vaults"] = {}
        (p.parent / "obsidian.json.miya-zaxira").write_text(matn, encoding="utf-8")
        for x in d["vaults"].values():
            x.pop("open", None)
        vid = secrets.token_hex(8)
        d["vaults"][vid] = {"path": v, "ts": int(time.time() * 1000), "open": True}
        tmp = p.with_suffix(".json.miya-tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        json.loads(tmp.read_text(encoding="utf-8"))          # yozilganini tekshirish
        os.replace(tmp, p)
        return "qoshildi"
    except (OSError, ValueError) as e:
        asos.log(f"obsidian ro'yxat xato: {type(e).__name__}: {e}")
        return "xato"


def och(vault: Path | None = None) -> str:
    """Vault'ni Obsidian'da ochadi: ro'yxatda bo'lmasa avval qo'shadi.
    Qaytadi: 'ochildi' | 'ilova-ochiq' (qo'lda: Open folder as vault) | 'xato'."""
    v = Path(vault or asos.vault()).resolve()
    holat = royxatga_qosh(v)
    if holat == "ilova-ochiq":
        return "ilova-ochiq"
    if holat == "xato":
        return "xato"
    try:
        if holat == "qoshildi":
            r = subprocess.run(["open", "-a", "Obsidian"], timeout=20)
        else:
            uri = ("obsidian://open?vault=" + urllib.parse.quote(v.name, safe="")
                   + "&file=" + urllib.parse.quote("BOSH-SAHIFA", safe=""))
            r = subprocess.run(["open", uri], timeout=20)
        return "ochildi" if r.returncode == 0 else "xato"
    except (OSError, subprocess.SubprocessError):
        return "xato"
