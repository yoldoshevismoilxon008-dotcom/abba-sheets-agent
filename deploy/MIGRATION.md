# VPS'ga ko'chirish — to'liq checklist

> Bot va kunlik 09:00 pipeline Mac'dan Linux serverga o'tadi. Hisobotlar vault'ga
> Mac'dagi soatlik sync orqali tushishda davom etadi. Rollback har doim mumkin.

## 0. VPS talablari

- **OS:** Debian 12 (tavsiya — apt'da normal chromium bor) yoki Ubuntu 22.04/24.04
  (chromium snap muammosida deploy.sh avtomatik Google Chrome .deb'ga o'tadi).
- **Resurs:** 2 GB RAM (claude CLI + Chrome headless uchun; 1 GB + swap ham yetadi,
  lekin sekin), 15+ GB disk, x86_64.
- **Kirish:** root SSH (deploy.sh root bilan ishlaydi) yoki sudo'li user.
- Serverda hech qanday kiruvchi port kerak emas (bot long-polling, hammasi chiquvchi).

## 1. Ko'chirishdan oldin (Mac'da)

- [ ] SSH kalit serverga qo'yilgan (`ssh-copy-id root@SERVER_IP`) — parolsiz kirish
      ham deploy, ham soatlik sync uchun shart (sync `BatchMode=yes` ishlatadi).
- [ ] **claude auth** (2-bo'limga qarang): Mac'da `claude setup-token` → chiqqan tokenni
      `.env` ga `CLAUDE_CODE_OAUTH_TOKEN=...` qatori qilib qo'shish. API-key yo'li
      27.11.2026 dan YO'Q (egasi qoidasi: faqat obuna limiti).
- [ ] `git status` toza, oxirgi kod commit qilingan.

## 2. claude -p auth: rejimlar va cheklovlar

**Asosiy rejim — Max plan OAuth token (`claude setup-token`):**
- Token **1 yil** yashaydi; brauzerli mashinada (Mac) yaratib, serverga env var
  sifatida ko'chirish rasmiy qo'llanadi (docs: "CI pipelines, scripts... where
  interactive browser login isn't available").
- `claude -p` headless rejim CI/cron uchun rasmiy mo'ljallangan.
- **Limitlar akkaunt bo'yicha umumiy**: Mac'dagi interaktiv sessiyalar + serverdagi
  kunlik hisobot/bot BITTA Max limitini (5-soatlik sessiya + haftalik) bo'lishadi.
  Server yuki kichik (kuniga 1 pipeline + bir nechta Q&A) — amalda sezilmaydi,
  lekin limit tugasa server so'rovlari ham yiqiladi (bizda har joyda fallback bor:
  hisobot quruq-raqam rejimida, bot xato xabari beradi).
- Parallel sessiya soni bo'yicha rasmiy cheklov hujjatlashtirilmagan; limit
  urilganda `claude -p` xato bilan qaytadi (run_claude exception → fallback).
- Token eskirsa (1 yil): Mac'da qayta `claude setup-token` → `.env` yangilash →
  `deploy.sh ... --code` emas, to'liq deploy (.env ni full rejim ko'chiradi).

**API key rejimi — 27.11.2026 dan O'CHIRILGAN (faqat obuna):**
- `ANTHROPIC_API_KEY` CLI'da har doim OAuth tokendan USTUN (rasmiy precedence; `-p` rejimida
  so'ramasdan ishlatiladi) — muhitga tasodifan tushsa, hamma `claude -p` jim API-billing'ga
  o'tardi. Endi `run_claude()` subprocess'ga `analyze.claude_env()` beradi: obunadan boshqa
  yo'lga o'tkaza oladigan o'zgaruvchilar (`analyze.api_billing_mi`: barcha `ANTHROPIC_*`,
  `CLAUDE_CODE_USE_*` va h.k.; faqat `CLAUDE_CODE_OAUTH_TOKEN` qoladi) olib tashlanadi. Ular
  `.env`, `.env.server` yoki Railway Variables'da tursa ham ishlatilmaydi.
- Tekshirish: botda `/claude` (faqat nomlar) va boot log'dagi `claude auth: …` qatori.
- Limit tugasa pul yechilmasligi uchun claude.ai → Settings → Usage'da «usage credits» o'chiq.

## 3. O'rnatish (VPS IP kelgach)

```bash
cd ~/abba-sheets-agent
./deploy/deploy.sh root@SERVER_IP        # to'liq: paketlar, user, kod, venv,
                                         # claude CLI, systemd, sinovlar
```

Skript oxirida 5 sinov o'tadi: Sheets o'qish → Chrome PDF (kerak bo'lsa
`--no-sandbox` avtomatik) → claude ping → **Dashboard yozuv** (service account
serverdan ham Editor ekanini tasdiqlaydi) → Telegram'ga "server'dan salom".
Sinov yiqilsa service'lar yoqilmaydi, Mac ishlashda davom etadi — xavfsiz.

Muvaffaqiyatdan keyin ham hech narsa avtomatik almashmaydi: server unit'lari
o'rnatilgan lekin **o'chiq**, Mac launchd ishlashda davom etadi.

## 4. Almashtirish (switchover)

```bash
./deploy/deploy.sh root@SERVER_IP --enable
```
Bu: serverda `abba-sheets-bot.service` + `abba-sheets-agent.timer` ni yoqadi,
Mac'da ikkala launchd'ni o'chiradi. (Ikkalasi bir vaqtda ishlashi mumkin emas:
Telegram polling 409 urushi + ikki nusxa hisobot.)

Keyin darhol Mac-sync o'rnatiladi (hisobotlar vault'ga tushishi uchun):
```bash
./deploy/mac-sync/install.sh root@SERVER_IP
```

- [ ] Botga savol yozib tekshirish (serverdan javob keladi).
- [ ] Ertasi 09:00 hisobot kelganini kuzatish (`journalctl -u abba-sheets-agent`).
- [ ] Soat o'tgach vault'da `abba-sheets-agent/hisobotlar/` yangilanganini ko'rish.

## 5. Kod yangilash (keyinchalik)

```bash
./deploy/deploy.sh root@SERVER_IP --code   # rsync + bot restart (data'ga tegmaydi)
```

## 6. Xavfsizlik (deploy.sh avtomatik qiladi)

- ufw: barcha kiruvchi yopiq (faqat SSH), chiquvchi ochiq.
- `.env` — 600, `credentials/` — 700/600, egasi `abba`.
- `.gitignore`: `.env`, `.env.server`, `credentials/`, `deploy/mac-sync/server.conf`
  — sirlar git'ga tushmaydi.
- Servicelar oddiy `abba` useridan ishlaydi (root emas).
- PM sheet'lar read-only scope'da qoladi; yozuv faqat dashboard allowlist orqali.

## 7. Rollback (server bilan muammo bo'lsa)

```bash
./deploy/deploy.sh root@SERVER_IP --rollback   # serverda o'chirish + Mac'da yoqish
```
Data yo'qolmaydi: server `data/` da to'plangan snapshotlar mac-sync orqali
hisobot darajasida Mac'da ham bor; to'liq snapshot json'lar kerak bo'lsa:
`rsync -az root@SERVER_IP:/home/abba/abba-sheets-agent/data/snapshots/ data/snapshots/`

## 8. Kuzatuv buyruqlari (serverda)

```bash
systemctl status abba-sheets-bot            # bot holati
journalctl -u abba-sheets-bot -f            # bot jonli log
systemctl list-timers abba-sheets-agent\*   # keyingi 09:00 qachon
journalctl -u abba-sheets-agent --since today
sudo -u abba tail -f /home/abba/abba-sheets-agent/data/logs/bot-$(date +%F).log
```

## Ochiq savollar / keyin

- Max plan headless server avtomatlashtirish siyosati rasmiy hujjatda aniq
  yozilmagan (texnik jihatdan setup-token aynan shu uchun). API-key rejimi
  27.11.2026 dan kodda bloklangan (egasi: faqat obuna) — qaytarish kod o'zgarishini
  talab qiladi (`analyze.api_billing_mi`).
- Server logs retention (data/logs cheksiz o'sadi) — hozircha muammo emas,
  keyin logrotate qo'shsa bo'ladi.
