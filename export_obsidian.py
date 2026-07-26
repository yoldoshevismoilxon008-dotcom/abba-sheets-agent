#!/usr/bin/env python3
"""Kunlik hisobotni Obsidian vault'dagi arxivga eksport qiladi (uzluksiz tarix).

data/snapshots/DATE/report.md →
  ~/claude-brain/abba-sheets-agent/hisobotlar/DATE.md
va hisobotlar/INDEX.md tepasiga link qo'shadi (eng yangisi birinchi, idempotent).

"O'zgarish yo'q" kunlarda ham yoziladi — tarix uzilmasin.
"""
import argparse
import os
import sys
from datetime import date
from pathlib import Path

BASE = Path(__file__).resolve().parent
SNAPSHOTS = Path(os.environ.get("DATA_DIR") or (BASE / "data")) / "snapshots"
VAULT_DIR = Path.home() / "claude-brain" / "abba-sheets-agent" / "hisobotlar"

INDEX_HEAD = [
    "# Abba Sheets Agent — kunlik hisobotlar arxivi",
    "",
    "> Har kunlik Telegram hisobotining nusxasi, eng yangisi tepada.",
    "",
]


def log(msg):
    print(f"[export] {msg}", flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", default=date.today().isoformat(), help="YYYY-MM-DD (default: bugun)")
    args = ap.parse_args()

    report = SNAPSHOTS / args.date / "report.md"
    if not report.exists():
        log(f"XATO: {report} yo'q — avval analyze.py ishga tushiring")
        return 1

    try:
        VAULT_DIR.mkdir(parents=True, exist_ok=True)
        body = report.read_text(encoding="utf-8").strip()
        out = VAULT_DIR / f"{args.date}.md"
        out.write_text(
            f"# {args.date} — Sheets kunlik hisobot\n\n{body}\n", encoding="utf-8"
        )
        log(f"yozildi: {out}")

        index = VAULT_DIR / "INDEX.md"
        # kunlik/YYYY-MM-DD.md bilan nom to'qnashuvi bo'lgani uchun to'liq yo'l + alias
        link = f"- [[abba-sheets-agent/hisobotlar/{args.date}|{args.date}]]"
        lines = (
            index.read_text(encoding="utf-8").splitlines() if index.exists() else list(INDEX_HEAD)
        )
        if link in lines:
            log("INDEX: bugungi link allaqachon bor")
        else:
            at = next((i for i, l in enumerate(lines) if l.startswith("- [[")), len(lines))
            lines.insert(at, link)
            index.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
            log(f"INDEX yangilandi: {link}")
    except OSError as e:
        log(f"XATO: vault'ga yozib bo'lmadi — {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
