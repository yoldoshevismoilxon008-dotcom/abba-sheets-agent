#!/usr/bin/env python3
"""Vault hisobotlar INDEX.md'sini to'ldiradi (vault_pull.sh dan keyin).

hisobotlar/ dagi har YYYY-MM-DD.md uchun INDEX'da link borligini ta'minlaydi —
export_obsidian.py bilan bir xil format, yangi sanalar tepada. Idempotent.
"""
import re
import sys
from pathlib import Path

VAULT_DIR = Path.home() / "claude-brain" / "abba-sheets-agent" / "hisobotlar"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
INDEX_HEAD = [
    "# Abba Sheets Agent — kunlik hisobotlar arxivi",
    "",
    "> Har kunlik Telegram hisobotining nusxasi, eng yangisi tepada.",
    "",
]


def main():
    if not VAULT_DIR.is_dir():
        return 0
    days = sorted(
        (p.stem for p in VAULT_DIR.glob("*.md") if DATE_RE.match(p.stem)), reverse=True
    )
    index = VAULT_DIR / "INDEX.md"
    lines = (
        index.read_text(encoding="utf-8").splitlines() if index.exists() else list(INDEX_HEAD)
    )
    added = 0
    for day in days:  # eng yangi birinchi — teskari tartibda tepaga kiradi
        link = f"- [[abba-sheets-agent/hisobotlar/{day}|{day}]]"
        if link in lines:
            continue
        at = next((i for i, l in enumerate(lines) if l.startswith("- [[")), len(lines))
        lines.insert(at, link)
        added += 1
    if added:
        index.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        print(f"[vault_index] {added} yangi link qo'shildi")
    return 0


if __name__ == "__main__":
    sys.exit(main())
