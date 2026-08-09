#!/bin/bash
# Obsidian "claude brain" vault → GitHub private repo push (Mac, har 10 daqiqa —
# launchd com.abba.brain-push). O'zgarish bo'lsagina commit+push; bo'lmasa jim
# (log shishmasin — no-change holati faqat status faylga yoziladi).
#
# Manba:  ~/claude-brain (git repo)
# Remote: ega tomonidan bir marta ulanadi (SSH tavsiya):
#   git -C ~/claude-brain remote add origin git@github.com:USER/claude-brain.git
#   git -C ~/claude-brain push -u origin main      # birinchi push qo'lda, auth tekshirish
#
# MAXFIYLIK: .kbignore (repo ildizi) → .git/info/exclude ga sinxronlanadi, undagi
# papkalar NA git'ga tushadi. .kbignore YO'Q bo'lsa push BUTUNLAY to'xtatiladi.
set -uo pipefail

VAULT="${BRAIN_VAULT:-$HOME/claude-brain}"     # BRAIN_VAULT — test uchun override
APP="$(cd "$(dirname "$0")/../.." && pwd)"
LOG="$APP/data/logs/brain-push.log"
STATUS="$APP/data/logs/brain-push-status.txt"
mkdir -p "$APP/data/logs"

note()  { echo "$(date '+%F %T') $*" >>"$LOG"; }     # LOG: faqat push/xato (o'smaydi)
stamp() { echo "$(date '+%F %T') $*" >"$STATUS"; }   # heartbeat: ustiga yoziladi

[ -d "$VAULT/.git" ] || { stamp "vault git repo emas — o'tkazildi"; exit 0; }

# Remote hali ulanmagan bo'lsa — jim no-op (bir marta ega ulaydi)
git -C "$VAULT" remote get-url origin >/dev/null 2>&1 \
    || { stamp "remote 'origin' yo'q — o'tkazildi"; exit 0; }

# .kbignore MAJBURIY — yo'q bo'lsa hech narsa push qilinmaydi (maxfiylik guard)
KBI="$VAULT/.kbignore"
[ -f "$KBI" ] || { stamp "XATO: .kbignore yo'q — push to'xtatildi"; note "XATO: .kbignore yo'q"; exit 0; }

# .kbignore + doimiy cruft → .git/info/exclude (git bu yo'llarni ko'rmaydi)
{
  echo "# AVTO-GENERATSIYA (brain-push.sh) — qo'lda tahrirlamang; .kbignore'ni tahrirlang."
  echo ".DS_Store"
  echo ".obsidian/"
  echo ".trash/"
  cat "$KBI"
} >"$VAULT/.git/info/exclude"

# .kbignore'ga keyin qo'shilgan, lekin allaqachon track qilingan fayllarni untrack
# (exclude faqat untracked fayllarga ta'sir qiladi — bu retroaktiv olib tashlaydi)
git -C "$VAULT" ls-files -ci --exclude-standard -z \
    | xargs -0 -r -I{} git -C "$VAULT" rm --cached -q -- {} 2>/dev/null || true

git -C "$VAULT" add -A
if git -C "$VAULT" diff --cached --quiet; then
  stamp "o'zgarish yo'q"                              # LOG'ga yozilmaydi → shishmaydi
  exit 0
fi

N=$(git -C "$VAULT" diff --cached --name-only | wc -l | tr -d ' ')
if ! git -C "$VAULT" -c user.name="brain-push" -c user.email="brain@abba.local" \
       commit -q -m "brain-sync $(date '+%F %H:%M')"; then
  note "commit yiqildi"; stamp "commit yiqildi"; exit 0
fi

if git -C "$VAULT" push -q origin HEAD 2>>"$LOG"; then
  note "push OK — $N fayl"; stamp "push OK — $N fayl"
else
  note "push yiqildi (tarmoq?) — keyingi safar qayta urinadi"; stamp "push yiqildi (tarmoq?)"
fi
exit 0
