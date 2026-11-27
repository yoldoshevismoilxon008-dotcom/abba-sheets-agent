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
4. **Guruh chat bo'lsa** (chat_id manfiy) — `TELEGRAM_OWNER_IDS=` ga buyruq bera oladigan
   odamlarning user ID'larini vergul bilan yozing. Aks holda bot guruhda hech kimga javob
   bermaydi (har bir a'zo `/pm_push`, `/pm_set` kabi buyruqlarni ishlata olmasin).
   Shaxsiy chatda bu shart emas.

### 4. config.yaml to'ldiring (siz qilasiz)

**Sheet ID'lar va `dashboard_id` — `config.yaml`'da EMAS** (repo public bo'lishi mumkin):
ular `config.local.yaml` (`.gitignore`'da) yoki Railway'da `CONFIG_LOCAL_B64` orqali
beriladi, sheet NOMI bo'yicha qo'shiladi:

```yaml
dashboard_id: "..."
sheet_ids:
  "Zubair PM KPI": "..."
```

Ega qarorlari ham shunday: `undiruv_qaror.json` (`.gitignore`'da, namuna —
`undiruv_qaror.example.json`), Railway'da `UNDIRUV_QAROR_B64`. Eski commit'dan yasash:
`python3 scripts/maxfiy_migratsiya.py`.

Har sheet uchun `config.yaml`'da: `name`, `mode: all_tabs` (barcha
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
  bloklanadi — `tests/test_p2_tuzatishlar.py` dagi `test_dashboard_writer_*`).
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

**Infografik Q&A-PDF:** raqamli-jadvalli javoblar (solishtirish, trend, oylik
natijalar, reyting/ro'yxat, KPI holat, `/audit`) kunlik hisobot brendidagi PDF
bo'lib keladi (`templates/qa-report.html`, active_theme ranglari). Chuqur
rejimda Claude javob turiga qarab o'zi tanlaydi: jadvalli javob — QA-JSON blok
(→ `render_pdf.render_qa`, `data/qa-pdf/`, 7 kunlik retention), matnli javob —
oddiy xabar. Fast rejim (bitta faktli savol) doim PDF'siz — tezlik saqlanadi.
Caption'da asosiy xulosa; PDF render yiqilsa javob JSON'dan yasalgan to'liq
matn bo'lib boradi (hech qachon yo'qolmaydi).

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
(hech qanday javob yo'q). Shu chat ichida ham yuboruvchi tekshiriladi: faqat
`TELEGRAM_OWNER_IDS` dagi (shaxsiy chatda — chat egasi) foydalanuvchi buyruq bera
oladi. `claude -p` toollarsiz va bo'sh papkada ishlaydi (sheet katagidagi ko'rsatma
fayl o'qita olmaydi); maxfiy tab o'qilgan javob xotira va arxivga yozilmaydi.

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

## 🗓 Kunlik reja va hisobot (`wow_kunlik.py`)

Bot (nomi faqat Telegram'da — `setMyName` yoki BotFather; kod uni `getMyName` dan o'qiydi, hozir **WALL-E**) har kuni ertalab **09:00–12:00** va kechqurun
**19:00–21:00** da har soat so'raydi (javob berilmaguncha): ertalab — «bugun qanday
ishlar qilasiz?», kechqurun — «nimalar qildingiz?» (ertalabki reja bilan).

1. Javob — **matn yoki ovoz** (`stt.py`: whisper.cpp + o'zbekcha rubaistt). Bir nechta
   xabar mumkin: har biri jadvalga qo'shiladi yoki uni tuzatadi («3-ni o'chir»).
2. `claude -p` (`prompts/wow-kunlik.md`) jadval tuzadi: ovozda buzilgan loyiha nomini oxirgi
   snapshot'dagi «Smm main» ro'yxatidagi yozilishi bilan ko'chiradi (qator boshida loyiha);
   botga savol bo'lsa — odatiy Q&A'ga yo'naltiradi. Claude ishlamasa — qatorlar bo'yicha
   oddiy bo'lish (⚠️ bilan).
   **Kalit so'zlar** (`kalitlar.py`, `/kalit`): egasining lug'ati — odamlar (ism — kimligi) va
   atamalar (so'z — ma'nosi). Ism va lavozimlar public repo'da emas: private Obsidian vault'dagi
   `abba-sheets-agent/kalit-sozlar.md` (vault_sync → `DATA/vault`), formati
   `## Bo'lim` + `- **Kalit** — ma'nosi`. Kalitlar whisper'ga `--prompt` bo'lib, lug'at esa
   Claude'ga beriladi.
3. `wow_jadval.py` — Google Sheets ko'rinishidagi PNG jadval (Pillow + `assets/fonts` Inter).
4. Preview + **✅ Yuborish / ❌ Bekor**. ✅ bosilganda yoki qoralama 15 daqiqa jim tursa,
   rasm egasining akkauntidan (`userbot_sender.send_photo`) boshliq lichkasiga ketadi.
   Yuborilmasa — rasm egaga keladi, «🔁 Qayta urinish» tugmasi bilan.

Buyruqlar: `/kunlik` (holat) · `/ertalab` · `/kechqurun` (hozir yozish; `qayta` —
yuborilganini yangilash) · `/dam` (bugun so'ramaslik) · `/kalit` (kalit so'zlar) · `/boshliq @username Ism`
(qabul qiluvchi; sinov — `/boshliq me`) · `/kunlik avto 15|off` · `/kunlik on|off`.

Holat — `DATA/wow_kunlik/<sana>.json`, sozlama — `DATA/wow_kunlik/sozlama.json` (volume).
Repo public: qabul qiluvchi kontakti kodda emas, faqat `/boshliq` bilan volume'ga yoziladi.
Yangi env shart emas (userbot — mavjud `TG_SESSION_STRING`, `TG_API_ID`, `TG_API_HASH`).

### 📌 Vazifa navbati (`vazifa.py`)

Egasining «keyin qilaman» ishlari va savollari. Botga tashlanadi, eslab qolinadi, ertalabki reja
so'rovi bilan har biri so'raladi.

1. **Qo'shish:** `/vazifa <matn>` · `/vazifa` yuborib, keyingi matn yoki ovoz (10 daqiqa;
   kunlik reja oynasida ham navbatga tushadi; boshqa buyruq yoki yangi kunlik so'rov kutishni
   bekor qiladi; kunlik so'rov/preview'ga aniq reply — kunlik oqimniki) · xabarga `/vazifa`
   bilan reply: matn, caption, «🎤 Eshitdim: «…»», ovozli xabar (matnga o'giriladi) yoki
   belgilangan iqtibos. Bitta xabardagi bir nechta ishni `claude -p` (`prompts/vazifa-ajrat.md`,
   effort low) alohida bandlarga ajratadi va nomlarni «Smm main» ro'yxati hamda egasining lug'ati
   bo'yicha tuzatadi (noaniq nom bo'lsa — ℹ️ izoh). Claude ishlamasa (yoki obuna limiti tugasa) —
   qatorlar bo'yicha oddiy bo'lish, ⚠️ bilan. Har qo'shishda «↩️ Bekor qilish» tugmasi.
   Restart'da xabar qayta ishlansa — ikki marta qo'shilmaydi va boshqa oqimga sirpanmaydi.
2. **So'rash:** ertalabki reja so'rovi yuborilgach (09:00 yoki birinchi muvaffaqiyatli so'rov,
   `/ertalab`, boot catch-up) — kuniga bir marta, ko'pi bilan 5 ta ish. Har biri alohida xabar:
   «Buni ham bugun qilasizmi?» **✅ Ha / ⏳ Keyinroq**. Eng uzoq so'ralmaganlar birinchi; ish
   xabari yetib borgandagina «so'raldi» hisoblanadi.
3. **✅ Ha** — ish bugungi ertalabki rejaga qo'shiladi va reja odatdagidek boshliqqa ketadi:
   - qoralama ochiq bo'lsa — darhol qator bo'lib, yangi preview bilan;
   - reja hali yozilmagan bo'lsa — egasi rejasini yozganda, xabardan reja chiqsa, jadval oxiriga
     («ok», «hozir yozaman» kabi xabar faqat navbat ishidan iborat qoralama ochmaydi);
   - reja yuborilgan bo'lsa — faqat «🔁 Rejaga qo'shib qayta yuborish» tugmasi bilan
     («yangilangan» qoralama; ish rejada bo'lsa tugma chiqmaydi; kechki so'rov boshlangan bo'lsa
     reja qayta ochilmaydi — ish kechki hisobotga qo'shiladi);
   - dam kuni, o'tkazilgan ertalab yoki 30 qatorli reja — navbatda qoladi.
4. **⏳ Keyinroq** — navbatda qoladi, keyingi kunlarda yana so'raladi.
5. **Kechqurun:** navbatdan bugunga olingan, lekin rejada yo'q ishlar kechki so'rovda ko'rsatiladi
   va kechki jadvalga (va «✅ Rejadagi hammasi bajarildi» ga) qo'shiladi. Hisobot boshliqqa
   yuborilgach: «bajarildi» bo'lgani yopiladi, qolgani navbatga qaytadi. `/kechqurun qayta` bilan
   tuzatilgan yoki ertasi kuni kech yuborilgan hisobot ham qayta solishtiriladi (olingan kuni
   bo'yicha; boot'da ham — uzilish bo'lsa). Hisobot bo'lmagan kun — ertalab navbatga qaytadi.
6. **Moslash qat'iy** (`wow_kunlik.matn_oxshash`): loyiha prefiksi («X:»), raqamlar va oy nomlari
   teng bo'lishi shart, qism/kengaytma — boshqa ish. Shubhada ish «bajarildi» bo'lmaydi.
7. `/vazifalar` — ro'yxat (sahifalab): ✅ bajarildi · 🗑 o'chirish · ❓ hozir so'rash. `/kunlik` da
   soni.

**Avto-yuborish himoyasi** (`wow_kunlik`, 27.11): preview egaga yetganda jadval izi (`korildi`)
saqlanadi. Avto-yuborish faqat jadval shu izga teng bo'lsa (egasi oxirgi o'zgarishni ko'rgan
bo'lsa) va jimlik lock ostida qayta tekshirilganda ham `AVTO_DAQ` bo'lsa ketadi. Aks holda —
avval yangi preview, sanoq qaytadan.

Holat — `DATA/wow_kunlik/vazifalar.json` (volume, atomik yozuv; buzilsa chetga olinadi, yangi
navbat ogohlantirish bilan darhol yoziladi va keyingi javobda egaga aytiladi; eski tugmalar
yangi ishlarga tegmaydi). Tugmalar — `vz:<amal>:<id>[:<sahifa>]`. Ish matnlari repo'da yo'q;
chat arxiviga (`chat_log`) bir qatordan tushadi — ikkinchi miyaga ham yetadi.

### 🔐 Claude — faqat obuna

`analyze.run_claude` `claude -p` ni `analyze.claude_env()` bilan ishga tushiradi: obunadan
boshqa yo'lga o'tkaza oladigan o'zgaruvchilar subprocess'ga berilmaydi (`analyze.api_billing_mi`:
barcha `ANTHROPIC_*`, `CLAUDE_CODE_USE_*`, `CLAUDE_CODE_API_KEY_*`, `CLAUDE_CODE_HOST_*`,
`CLAUDE_CODE_SKIP_*_AUTH`, `AWS_BEARER_TOKEN_BEDROCK`, `CLAUDE_CODE_SIMPLE` va h.k.; faqat
`CLAUDE_CODE_OAUTH_TOKEN` qoladi). CLI qo'llasa `--setting-sources project` — foydalanuvchi
sozlamalaridagi `apiKeyHelper`/env ham yuklanmaydi. Railway'da `CLAUDE_CODE_OAUTH_TOKEN`, Mac'da
claude.ai login. `/claude` — holat (faqat nomlar; `claude auth status` tasdig'i bilan), boot
log'da `claude auth: …` qatori. Limit tugasa pul yechilmasligi uchun claude.ai → Settings →
Usage'da «usage credits» o'chiq bo'lishi kerak.

## 🖥 VPS'ga ko'chirish (deploy/)

Tizim server-portable: `deploy/deploy.sh root@IP` — to'liq o'rnatish (paketlar,
chromium, `abba` user, venv, claude CLI, systemd unit'lar, ufw) + 5 sinov
(Sheets / Chrome-PDF / claude / Dashboard yozuv / Telegram salom). Service'lar
avtomatik yoqilmaydi — almashtirish `--enable` bilan (Mac launchd'ni o'zi
o'chiradi), qaytish `--rollback`. Hisobotlar vault'ga Mac'dagi soatlik
`deploy/mac-sync/` job orqali tushadi. To'liq checklist va claude auth
(setup-token; API-key rejimi 27.11.2026 dan o'chirilgan) tafsilotlari: **`deploy/MIGRATION.md`**.
