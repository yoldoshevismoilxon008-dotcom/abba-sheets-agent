# abba-sheets-agent

Google Sheets kunlik monitoring agenti: har kuni **09:00** da config'dagi
sheetlarni o'qiydi, kechagi snapshot bilan solishtiradi, `claude -p` bilan
tahlil qiladi va Telegram'ga o'zbekcha hisobot yuboradi.

```
fetch.py → diff.py → analyze.py (claude -p) → send.py
   │          │            │                    │
snapshot   diff.json    report.md           Telegram
        (data/snapshots/YYYY-MM-DD/)
```

- Snapshotlar 30 kun saqlanadi (eski papkalar avtomatik o'chadi).
- Bir sheet o'qilmasa — skip + log, qolganlari davom etadi.
- Claude ishlamay qolsa — quruq raqamlardan fallback hisobot ketadi.
- Pipeline'ning istalgan bosqichi yiqilsa — Telegram'ga ⚠️ alert boradi.
- O'zgarish bo'lmagan kunda Claude chaqirilmaydi, "o'zgarish yo'q" xabari ketadi.

---

## O'rnatish checklist

### 1. Python muhiti (bajarilgan ✅)

```bash
cd ~/abba-sheets-agent
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

### 2. Google service account (siz qilasiz)

1. [console.cloud.google.com](https://console.cloud.google.com) → loyiha tanlang yoki yangi yarating.
2. **APIs & Services → Library** → "Google Sheets API" → **Enable**.
3. **APIs & Services → Credentials → Create Credentials → Service account**
   (nom: `abba-sheets-agent`, rol shart emas) → yaratib bo'lgach service
   account ichida **Keys → Add key → Create new key → JSON** → yuklab oling.
4. Faylni shu yerga qo'ying: `~/abba-sheets-agent/credentials/service-account.json`
5. JSON ichidagi `client_email` (…@…iam.gserviceaccount.com) manzilini nusxalab,
   **har bir kuzatiladigan sheet'ga Share → Viewer** qilib bering.

### 3. Telegram bot (siz qilasiz)

1. Telegram'da [@BotFather](https://t.me/BotFather) → `/newbot` → nom bering →
   token'ni `.env` dagi `TELEGRAM_BOT_TOKEN=` ga yozing.
2. Yangi botingizga Telegram'da **/start** deb yozing
   (guruhga yubormoqchi bo'lsangiz — botni guruhga qo'shib, guruhda xabar yozing).
3. Chat ID toping:
   ```bash
   venv/bin/python send.py --get-chat-id
   ```
   Chiqqan `chat_id` ni `.env` dagi `TELEGRAM_CHAT_ID=` ga yozing.

### 4. config.yaml to'ldiring (siz qilasiz)

Har sheet uchun: `id` (URL'dagi uzun ID), `name`, `mode: all_tabs` (barcha
tab'lar avtomatik o'qiladi), `watch_tabs: auto` (kunlik diff uchun Main +
joriy oy tabi NOMDAN avtomatik topiladi — oy almashganda config'ga tegish
shart emas), `watch` (tahlil izohyi), `key_column` (semantik: `main:` /
`month:` kalitlari yoki tab nomi). Eski uslub (`ranges` ro'yxati) ham ishlaydi.

`kpi_enabled: false` — KPI pul hisob-kitoblari `prompts/kpi-qoidalar.md`
tasdiqlanmagunicha o'chiq (Claude'ga "KPI tasdiqlayman" deyilganda true qilinadi).

### 5. Sinov

```bash
cd ~/abba-sheets-agent
venv/bin/python fetch.py            # sheetlar o'qilyaptimi?
venv/bin/python diff.py             # birinchi kun: baseline
venv/bin/python analyze.py          # report.md yaratiladi
venv/bin/python send.py --dry-run   # yubormasdan ko'rish
venv/bin/python send.py             # real yuborish
# yoki hammasi birdan:
./run.sh
```

### 6. launchd — har kuni 09:00 (siz qilasiz)

```bash
cp ~/abba-sheets-agent/launchd/com.abba.sheets-agent.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.abba.sheets-agent.plist

# tekshirish:
launchctl print gui/$(id -u)/com.abba.sheets-agent | head -20
# qo'lda ishga tushirib ko'rish:
launchctl kickstart gui/$(id -u)/com.abba.sheets-agent
# o'chirish kerak bo'lsa:
launchctl bootout gui/$(id -u)/com.abba.sheets-agent
```

**Uyqu haqida:** Mac 09:00 da uxlab yotgan bo'lsa, launchd o'tkazib yuborilgan
ishni **uyg'ongan zahoti bir marta** bajaradi. Mac umuman o'chiq bo'lsa — ishlamaydi.
Xohlasangiz, Mac'ni har kuni 08:58 da uyg'otish uchun:

```bash
sudo pmset repeat wakeorpoweron MTWRFSU 08:58:00
```

---

## Kundalik fayllar

| Yo'l | Nima |
|---|---|
| `data/snapshots/YYYY-MM-DD/<SHEET_ID>.json` | O'sha kungi xom snapshot |
| `data/snapshots/YYYY-MM-DD/diff.json` | Kechagi bilan farq (added/removed/changed) |
| `data/snapshots/YYYY-MM-DD/report.md` | Claude yozgan hisobot |
| `data/snapshots/YYYY-MM-DD/_meta.json` | Fetch natijasi/xatolari |
| `data/logs/YYYY-MM-DD.log` | Shu kungi pipeline logi |
| `data/logs/launchd.log` | launchd darajasidagi log |

## 🔒 Xavfsizlik modeli (read-only kafolat)

- **O'qish:** `fetch.py` (va undan foydalanadigan hamma narsa) faqat
  `spreadsheets.readonly` scope bilan ishlaydi — PM sheet'lariga yozish
  texnik jihatdan MUMKIN EMAS.
- **Yozish:** faqat `dashboard_writer.py` orqali va faqat `config.yaml` dagi
  `dashboard_id` ga (qat'iy allowlist). Boshqa istalgan sheet'ga yozish
  urinishi: exception + log + Telegram'ga 🚨 alert (tarmoqqa chiqmasdan
  bloklanadi — unit-test bilan isbotlangan).
- **SA huquqlari qoidasi:** PM sheet'larda faqat **Viewer**, dashboard'da
  **Editor** — bu qoida buzilmasin.

## 📊 Dashboard

`dashboard.py` kunlik run oxirida (yoki qo'lda) dashboard sheet'ini to'ldiradi:
**Umumiy** (har PM holati, overwrite) · **Trend** (kunlik qatorlar, sana+PM
bo'yicha idempotent append — grafiklar bazasi) · **Audit** (oxirgi topilmalar) ·
**KPI** (qoidalar holati, stavkalar, prognoz). Sarlavhalar barqaror —
grafiklaringiz buzilmaydi. Sinov: `dashboard.py --dry-run`.
Botda `/dashboard` — link + oxirgi yangilanish vaqti.

## Muammolarni aniqlash

- Hisobot kelmadi → `tail -50 data/logs/$(date +%F).log`
- "sheet o'qilmadi" → sheet service account email'iga share qilinganini va
  Sheets API yoqilganini tekshiring.
- Chat topilmadi (`--get-chat-id`) → botga /start yozib qayta uriming.
- Claude xatosi → `.env` da `CLAUDE_BIN=/opt/homebrew/bin/claude` ni oching;
  fallback hisobot baribir yuborilgan bo'ladi.
- `.env` / `credentials/` / `data/` — `.gitignore` da, git'ga tushmaydi.

## Test (mock ma'lumot bilan)

```bash
venv/bin/python tests/make_mocks.py       # 3 kunlik soxta snapshotlar
venv/bin/python diff.py --date 2026-07-15 # o'zgarishlar diff'i
venv/bin/python analyze.py --date 2026-07-15
venv/bin/python send.py --date 2026-07-15 --dry-run
rm -rf data/snapshots/2026-07-1{4,5,6}    # tozalash
```

---

## 🤖 Q&A rejimi (bot_listener.py)

Botga oddiy tilda savol yozing — sheet'larning **joriy** holati asosida javob
beradi ("Zubairda Livardi bormi?", "qaysi loyihalarda deadline o'tgan?").
Har savolda sheet'lar jonli o'qiladi, lekin kunlik snapshot'larga **yozilmaydi**
(09:00 zanjiri buzilmaydi). Jonli o'qish yiqilsa — oxirgi snapshot'dan javob
beradi, "(oxirgi snapshot: SANA)" belgisi bilan.

Savolga qarab kerakli sheet/tab'lar tanlanadi: PM ismi aytilsa — faqat o'sha
sheet; oy nomlari aytilsa ("oktabrdan iyungacha" kabi oraliq ham) — o'sha oy
tab'lari; default — Main (bo'lsa) + joriy oy.

**Suhbat xotirasi:** oxirgi 10 savol-javob promptda (`data/bot-memory/history.jsonl`) —
"nega?", "o'shani batafsilroq", "bunga javob bermading" kabi davom savollari
ishlaydi. `/yangi` — kontekstni tozalash. **Ikki rejim:** oddiy savol — tez;
murakkab (nega/solishtir/trend/ko'p oy/davom savoli) — chuqur tafakkur
(effort=max) + tarixiy snapshotlar (`data/snapshots/`) kontekstga ulanadi.
KPI qoidalari va oxirgi audit natijasi (`data/last-audit.md`) doim kontekstda.
Javob yuborish 4 urinishli retry bilan (Mac uyqudan uyg'onganda tarmoq kech
tiklanadi); yuborilmagan javob `data/bot-outbox.md` ga tushadi.

**Buyruqlar:** `/hisobot` — hisobotni hozir yaratib yuborish (oxirgi snapshot'ga
nisbatan diff, snapshot yozmasdan); `/audit` — data sifat auditi (bo'sh majburiy
kataklar, yilsiz sanalar, raqam o'rnida matn, Jami=0 muammosi, nomsiz qatorlar,
tab'lararo nomuvofiqlik); `/help` — misol savollar; qolgan har qanday matn — savol.

**Data audit jadvali:** har dushanba 09:00 hisobotiga to'liq audit bo'limi
qo'shiladi; boshqa kunlari faqat kritik topilmalar bo'lsa 1 qatorlik eslatma.

**Tan olingan muammolar (ack):** `/ack <kalit> [izoh]` — ma'lum muammoni tan
olish (masalan `/ack main-tab-yoq jamoa bilan muhokamada`); u endi KRITIK deb
takrorlanmaydi, hisobotlarda "🤝 Tan olingan" qisqa qatorida ko'rinadi.
`/ack` — ro'yxat + mavjud kalitlar. Fayl: `data/audit-acknowledged.yaml`.
Muammo sheet'da tuzalsa topilma o'z-o'zidan yo'qoladi (ack yozuvi bekor turadi).

**Main o'rniga vaqtinchalik manba:** Main tabi yo'q sheet'larda watch avtomatik
"Loyihalarning ishlash muddati" tabiga o'tadi (deadline/muddat savollari shu
tabdan javob oladi); Main qaytarilsa avvalgi holat o'z-o'zidan tiklanadi.

**Xavfsizlik:** bot faqat `.env` dagi `TELEGRAM_CHAT_ID` ga javob beradi.
Boshqa chat'lardan kelgan xabarlar log qilinadi va **jim** ignore bo'ladi
(hech qanday javob yo'q).

**launchd (doimiy fon):**
```bash
cp launchd/com.abba.sheets-bot.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.abba.sheets-bot.plist
# holat:      launchctl print gui/$(id -u)/com.abba.sheets-bot | grep state
# restart:    launchctl kickstart -k gui/$(id -u)/com.abba.sheets-bot
# to'xtatish: launchctl bootout gui/$(id -u)/com.abba.sheets-bot
```
`KeepAlive=true` — listener o'lsa launchd avtomatik qayta ko'taradi.

**Loglar:** `data/logs/bot-YYYY-MM-DD.log` (listener) va `data/logs/bot-launchd.log`.

**⚠️ Muhim:** listener ishlab turganda `send.py --get-chat-id` ishlatmang —
ikkalasi ham `getUpdates` chaqiradi, Telegram 409 conflict beradi (listener
buni logda ko'rsatib kutadi, lekin chat_id qidiruv ham ishlamaydi). Kerak
bo'lsa avval `launchctl bootout`, keyin qidiring.

**Offset:** `data/bot-state.json` da `last_update_id` saqlanadi — xabar hech
qachon ikki marta ishlanmaydi; birinchi ishga tushishda eski backlog tashlab
yuboriladi (restart'da eski xabarlar qayta o'qilmaydi).
