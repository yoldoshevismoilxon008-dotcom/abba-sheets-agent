# Railway'ga ko'chirish — reja, qadamlar, cutover, qabul testi

> Arxitektura: **bitta service** (Dockerfile) — `supervisor.py` ichida bot listener
> (asosiy thread) + APScheduler (09:00 Asia/Tashkent → `run.sh`). Barcha state
> `DATA_DIR=/data` (Railway volume). Kod: private GitHub repo, **push = deploy**.
> Hisobotlar: server har kunlik pipeline'dan keyin ikkinchi private repo'ga
> `hisobotlar/*.md` push qiladi; Mac'dagi soatlik launchd job uni vault'ga tortadi.
> Mac'da faqat yordamchi joblar qoladi — pastdagi «Joriy holat» jadvaliga qarang.
> Plist fayllari o'chirilmaydi, shuning uchun rollback bir buyruq.

## Joriy holat — 07.09.2026 (cutover BAJARILGAN)

Bot va 09:00 kunlik pipeline **Railway'da**; Mac'da faqat vault sinxronizatsiyasi qoldi.

| Job / bosqich | Qayerda | Jadval | Izoh |
|---|---|---|---|
| Kunlik pipeline (`run.sh`) | **Railway** | 09:00 (Asia/Tashkent) | supervisor APScheduler |
| Telegram bot (listener) | **Railway** | doimiy | supervisor asosiy thread |
| PM undiruv push (`pm_push`) | **Railway** | 09:30 | faqat supervisor'da — `run.sh` uni chaqirmaydi, Mac'da bu bosqich umuman mavjud emas |
| Hisobotlar repo'ga push | **Railway** | pipeline'dan keyin | `push_reports.py`; `run.sh` da chaqiruv yo'q, shuning uchun `abba-hisobotlar` dagi har commit — Railway tirikligining isboti |
| `com.abba.reports-pull` | Mac | har 10 daq | hisobotlar repo → vault rsync |
| `com.abba.brain-push` | Mac | har 10 daq | vault → GitHub (`claude-brain`) |
| `com.abba.tg-kunlik` | Mac | 08:30 | **boshqa loyiha** (`~/.abba-tg-audit`), bu repoga aloqasi yo'q |
| `com.abba.sheets-agent` | ❌ disabled | — | 07.09.2026 da o'chirildi |
| `com.abba.sheets-bot` | ❌ disabled | — | 07.09.2026 da o'chirildi |

### Nega o'chirildi (07.09.2026)

Cutover'dan keyin Mac joblari **yoqilgan qolib ketgan** edi — ikki nusxa parallel ishladi:

- **Bot:** bitta Telegram tokenida ikkita poller. `getUpdates` **409 conflict**
  bugungi logda **771 marta**, bot Mac'da shu holatda **7 kun 18 soat** ishlagan —
  buyruqlar ikki instansiya orasida tasodifiy taqsimlangan.
- **Pipeline:** ikkala tomon ham o'z `claude -p` analizini qilib, egaga **ikkita
  har xil hisobot** yuborgan. (07.09 da Mac nusxasi matn rejimida ketdi — o'sha
  kuni PDF render yiqilgan.)

### Tekshiruv — farq darhol ko'rinsin

```bash
launchctl list | grep abba
```
Kutilgan chiqish — aynan **uchta** qator:
```
-	0	com.abba.reports-pull
-	0	com.abba.tg-kunlik
-	0	com.abba.brain-push
```
Agar ro'yxatda `com.abba.sheets-agent` yoki `com.abba.sheets-bot` **paydo bo'lsa**,
ikki nusxa yana ishlayapti — pastdagi buyruq bilan o'chiring.
`disable` holatini alohida tekshirish: `launchctl print-disabled gui/$(id -u) | grep abba`

### O'chirish va rollback

```bash
# O'chirish (07.09.2026 da aynan shunday qilindi):
launchctl bootout gui/$(id -u)/com.abba.sheets-bot
launchctl disable gui/$(id -u)/com.abba.sheets-bot
launchctl bootout gui/$(id -u)/com.abba.sheets-agent
launchctl disable gui/$(id -u)/com.abba.sheets-agent

# Rollback (Railway to'xtasa) — `enable` MAJBURIY:
# disabled holatdagi jobni `bootstrap` yuklamaydi, jimgina e'tiborsiz qoldiradi.
launchctl enable    gui/$(id -u)/com.abba.sheets-bot
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.abba.sheets-bot.plist
launchctl enable    gui/$(id -u)/com.abba.sheets-agent
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.abba.sheets-agent.plist
```
Rollback'dan oldin Railway tomonni to'xtating (bot tokenini olib tashlab redeploy
yoki deploy'ni o'chirish) — aks holda yana 409 boshlanadi.

## Nima tayyor (kod tomonida)

- `Dockerfile` — python:3.12-slim + chromium (`--no-sandbox --disable-dev-shm-usage`
  konteyner uchun majburiy) + fontlar + node/npm + claude CLI; `.dockerignore`
  sirlar va lokal data'ni image'dan chetlatadi.
- `supervisor.py` — boot'da: `GOOGLE_SA_JSON` (base64) → `/data/credentials/…`,
  brand seed (image → volume, tasdiqlangan dizayn ustun), holat seed
  (`seed/`: ack ro'yxati + bot xotirasi — bir martalik), keyin scheduler + bot.
- `DATA_DIR` env barcha modullarda: snapshots, bot-memory, bot-state, ack,
  qa-pdf, logs, credentials, brand — hammasi volume'da.
- `push_reports.py` — hisobotlarni `REPORTS_REPO`ga push (idempotent).
- `deploy/railway/` — Mac tomoni: `install.sh <repo-url>` soatlik pull + vault INDEX.

## SIZ QILADIGAN QADAMLAR (tartib bilan)

### 1. claude token (Mac terminalda)
```bash
claude setup-token        # brauzer ochiladi → ruxsat → token chiqadi
```
Chiqqan `sk-ant-oat...` tokenni nusxalab oling — 5-qadamda Railway'ga qo'yiladi.
(1 yil yashaydi; hech qayerga fayl qilib saqlamang.)

### 2. GitHub — ikkita PRIVATE repo
[github.com/new](https://github.com/new) da:
- `abba-sheets-agent` — **Private**, bo'sh (README'siz).
- `abba-hisobotlar` — **Private**, bo'sh. (Diqqat: kod repo'sida `seed/` ichida
  bot suhbat xotirasi bor — repo'lar albatta private bo'lsin.)

Keyin menga ayting — men push qilaman. (Yoki o'zingiz:
```bash
cd ~/abba-sheets-agent
git remote add origin git@github.com:SIZNING_USER/abba-sheets-agent.git
git push -u origin main
```
)

### 3. Hisobotlar uchun PAT (fine-grained token)
GitHub → Settings → Developer settings → **Fine-grained tokens** → Generate:
- Repository access: **Only select** → `abba-hisobotlar`
- Permissions → Repository → **Contents: Read and write**
- Expiration: 1 yil. Tokenni nusxalang (5-qadamda `GH_TOKEN_REPORTS`).

### 4. Service account base64 (Mac terminalda)
```bash
base64 -i ~/abba-sheets-agent/credentials/service-account.json | pbcopy
```
Buferda — 5-qadamda `GOOGLE_SA_JSON` bo'ladi.

### 5. Railway project
[railway.app](https://railway.app) → **New Project → Deploy from GitHub repo** →
`abba-sheets-agent` ni ulang. Keyin service'da:
- **Volume**: Add Volume → mount path: `/data` (1 GB yetadi).
- **Settings → Restart policy: Always** (bot doim tiklansin). Serverless/App
  Sleep bo'lsa — O'CHIQ (bot uzluksiz polling qiladi).
- **Variables** (Raw editor'ga birdan qo'yish qulay):
  ```
  TELEGRAM_BOT_TOKEN=...       (Mac .env'dagi bilan bir xil)
  TELEGRAM_CHAT_ID=...
  TELEGRAM_OWNER_IDS=...       (faqat GURUH chat bo'lsa: buyruq beruvchilar user ID'lari, vergul bilan)
  CLAUDE_CODE_OAUTH_TOKEN=...  (1-qadamdan)
  GOOGLE_SA_JSON=...           (4-qadamdan, bitta uzun qator)
  REPORTS_REPO=SIZNING_USER/abba-hisobotlar
  GH_TOKEN_REPORTS=...         (3-qadamdan)
  ```
  (`DATA_DIR=/data`, `CHROME_*`, `TZ` — Dockerfile'da, qo'yish shart emas.)

**Hali deploy tugashini kutmang / bot ishga tushsa ham xavotir yo'q** — pastdagi
cutover'gacha Mac listener ishlab turgani uchun Telegram'da 409-raqobat bo'lishi
mumkin, bu qisqa va zararsiz, lekin to'g'ri tartib — avval Mac'ni o'chirish:

## CUTOVER (409 conflict'siz almashtirish tartibi)

Ikkita listener bitta botda ishlay olmaydi (getUpdates 409). Tartib:

```bash
# 1. Mac listener + kunlik jobni o'chirish (plist fayllar joyida qoladi):
launchctl bootout gui/$(id -u)/com.abba.sheets-bot
launchctl disable gui/$(id -u)/com.abba.sheets-bot
launchctl bootout gui/$(id -u)/com.abba.sheets-agent
launchctl disable gui/$(id -u)/com.abba.sheets-agent

# 2. Railway'da deploy yashil bo'lishini kutish (Deployments → Active).
#    Log'da ko'rinishi kerak: "[supervisor] scheduler tayyor" va "listener boshlandi".

# 3. Telefondan test (pastdagi QABUL TESTI).

# 4. Hisobot-pull o'rnatish (vault to'ldirilishi uchun):
cd ~/abba-sheets-agent && ./deploy/railway/install.sh git@github.com:SIZNING_USER/abba-hisobotlar.git
```

### ROLLBACK (5 daqiqa)
```bash
# Railway'da: service → Settings → Remove deploy (yoki Variables'da bot tokenni
# vaqtincha o'chirib redeploy — listener to'xtaydi). Keyin Mac'da:
launchctl enable    gui/$(id -u)/com.abba.sheets-bot
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.abba.sheets-bot.plist
launchctl enable    gui/$(id -u)/com.abba.sheets-agent
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.abba.sheets-agent.plist
```
> `enable` siz `bootstrap` disabled job'ni yuklamaydi (07.09.2026 dan beri
> ikkalasi ham `disable` holatida) — shuning uchun ikkala qator ham kerak.
Server volume'dagi yangi snapshotlar Mac'da bo'lmaydi (hisobotlar repo orqali
matni bor) — qaytgach birinchi kun diff bo'sh tarixdan boshlanishi mumkin, kritik emas.

## QABUL TESTI (Mac YOPIQ holda, telefondan)

| # | Amal | Kutilgan natija |
|---|---|---|
| 1 | `Zubairda Livardi loyihasi bormi?` | Tez matnli javob (fast rejim) |
| 2 | `bu yildagi har bir oylarning natijalarini taqdim et` | Infografik PDF (2-3 daqiqa, deep) |
| 3 | `/hisobot` | Oraliq hisobot (PDF yoki "o'zgarish yo'q") |
| 4 | `/audit` | Strukturali audit PDF |
| 5 | Ertasi 09:00 | Kunlik PDF hisobot avtomatik keladi |
| 6 | 09:00 dan keyin ~1 soat ichida | Vault `hisobotlar/` da yangi kun fayli (Mac yoqilganda) |

1-4 o'tsa — ko'chirish muvaffaqiyatli. 5-6 — ertasi kuni tasdiqlanadi.

## Kundalik ishlatish (ko'chirilgandan keyin)

- **Kod o'zgarishi**: men Mac'da commit qilaman → `git push` → Railway avto-deploy
  (~3-5 daqiqa). Data/volume'ga tegilmaydi.
- **Log ko'rish**: Railway → service → Logs (run.sh chiqishi ham shu yerda, LOG_TEE).
- **Dizayn (/dizayn, logo)**: avvalgidek bot orqali — natija volume'da saqlanadi,
  redeploy'da yo'qolmaydi (brand seed faqat yo'q fayllarni to'ldiradi).
- **claude limitlari**: Max akkaunt limiti Mac + Railway umumiy (MIGRATION.md
  2-bo'limga qarang); token 1 yildan keyin yangilanadi (setup-token → Railway var).
- **Xarajat**: hobby plan ~$5/oy atrofida (bitta doimiy service + 1GB volume;
  claude API xarajati yo'q — Max plan token).

## Undiruv: oy oxiri ko'chirish ro'yxati (AUDIT P0-3)

Oy oxirida (oxirgi 6 kun) 💰 blok «🔁 <oy> tabiga ko'chirilgan» deb ko'rsatgan qarzlar
keyingi oyda ham eslab qolinadi (`undiruv_carry.py`): o'tgan oy qatori ochiq qolsa, PM'dan
IKKINCHI marta so'ralmaydi, egaga har kuni «⚠️ Ikki tabda dublikat» chiqadi; ko'chirilgan
qatordan pul izsiz yo'qolsa — «$N izohsiz».

- **Holat fayli:** `/data/undiruv_carry/<YYYY-MM>.json` (YYYY-MM — ro'yxat tuzilgan oy, masalan
  `2026-09.json` oktabr uchun). Bu **volume holati — git'ga HECH QACHON qo'shilmaydi**: repo
  public, faylda mijoz nomlari va summalar bor (`data/*` .gitignore'da).
- **Qachon yoziladi:** keyingi oyning birinchi undiruv o'qishida (09:00 run, 09:30 push,
  /hisobot yoki dashboard — qaysi biri birinchi bo'lsa) **bir marta** muzlatiladi, manbasi —
  o'tgan oy oxirgi faol kunining `snapshots/<kun>/report.json`i. Keyin o'zgarmaydi.
  Kelajak sanali simulyatsiya (`pm_push.py --dry-run --date 2026-11-01` 28.10 da) faylni
  **muzlatmaydi** — real sana oy oxiridan o'tmaguncha ro'yxat faqat xotirada quriladi.
- **Qayta qurish:** faylni o'chiring — keyingi o'qishda `snapshots/<oy oxiri>/report.json`dan
  qayta tuziladi. Bu faqat o'sha papka turgan paytda ishlaydi: retention 40 kun (30.09 papkasi
  **10.11 09:00 run oxirida** o'chadi; 30 kunlik eski retention'da — 31.10).
- **Buzilgan fayl:** bot o'zi tuzatmaydi — 💰 blokda «⚠️ undiruv_carry/… buzilgan» chiqadi va
  qarzlar odatdagidek so'raladi. Faylni o'chiring (yuqoridagi qayta qurish).
- **Kill switch:** Railway Variables'da `UNDIRUV_CARRY_OFF=1` → redeploy. P0-3 qo'shimchalarining
  hammasi o'chadi (dublikat/izohsiz, 1–10 kunlik o'tgan tab kuzatuvi, 💰dagi «⚖️ Summa farqli»),
  xulq 69a8de7 bilan bir xil. Fayl o'chirilmaydi — kalit olinsa yana ishlatiladi.
- **Muzlatishdan oldin `analyze.py --date <oy oxiri>` ni ishga tushirmang:** `summary` jonli
  ma'lumotdan o'qiydi va o'sha kunning report.json ro'yxatini BUGUNGI holat bilan qayta yozadi.

**Birinchi deploy (sentabr → oktabr):** 31.10 09:00 dan OLDIN (aks holda 30.09 snapshot'i
o'chib, oktabr eski xulqda qoladi). Avval zaxira:
```bash
mkdir -p /data/keep && cp -r /data/snapshots/2026-09-30 /data/snapshots/2026-10-01 /data/snapshots/2026-10-02 /data/keep/
python3 -c "import json;d=json.load(open('/data/snapshots/2026-09-30/report.json'));print([(i['loyiha'],i['summa'],i['yangi_muddat']) for i in d['undiruv']['keyingi']['kochgan']])"
```
Ro'yxatda `('Bosimov shcool', 2500, '18.10')` bo'lishi kerak. Deploy'dan keyin (bu buyruq faylni
o'zi muzlatadi ham):
```bash
cd /app && venv/bin/python -c "import undiruv_carry as c; from datetime import date; print(c.royxat(date(2026,10,13)))"
ls -l /data/undiruv_carry/2026-09.json
```
Chiqishda `Bosimov shcool` 2500 → `Bosimov School` 18.10 bo'lishi, `baza` — `snapshot:2026-09-30`.

## Undiruv: Kelishilgan izohsiz kamayishi (AUDIT P0-5)

09:00 💰 blok (report.md, report.json, kunlik PDF, caption, /hisobot) joriy oy tabini **qatorma-qator
kecha ↔ bugun** tekshiradi (`undiruv_izohsiz.py`). Har qatorda Summa + Undirildi + Lose summa + Aktive
Summary o'zgarmasligi kerak (Summa — qolgan qarz). Kamaysa — «⚠️ Izohsiz yo'qolish: <Loyiha> (<PM>) $X,
muddat DD.MM», qator o'chsa — «⚠️ Qator o'chirilgan», keyin Undirildi/Lose/Aktive yozilsa, Summa aynan
qaytarilsa, qator jami yo'qolishdan oldingi jamiga qaytsa (Summa qisman + Undirildi) yoki holat «Ega
qarori» bo'lsa — «✅ … izohlandi»; aks holda oy oxirigacha har kuni «⚠️ … hali izohlanmagan» satrida
takrorlanadi. O'chirilgan qator boshqa imlo bilan qaytsa («Icar24» → «Icar 24») ham qayta bog'lanadi.
💰 qatorida « · lose $L · izohsiz yo'qolgan $X (oy boshidan) · lose va izohsiz hisobga olinsa P%», PDF'da
«Lose · izohsiz» KPI (ostida «izohsiz oy boshidan») va Bajarilish ostida «lose+izohsiz bilan P%»,
caption'da « · ⚠️ izohsiz $X».

- **Holat fayli YO'Q:** hodisalar har summary() chaqiruvida `/data/snapshots/<kun>/<sheet>.json`
  dan qayta quriladi — asos: 1-sanadan oldingi (≤7 kun) shu oy tabi bor oxirgi snapshot, keyin har
  snapshot kuni juft-juft. Qatorma-qator satrlar snapshot'lardan deterministik, kod tuzatilsa tarix ham
  o'zi to'g'rilanadi; tozalash yoki qayta qurish kerak emas. `fetch.py --date D` eski snapshot'ni qayta
  yozsa — o'sha kundan keyingi hodisalar shu yangi ma'lumotdan qayta hisoblanadi.
- **O'tgan kunni ko'rish — faqat quyidagi CLI** (snapshot'dan, faqat o'qiydi). `analyze.py --date D`
  ISHLATMANG: u 💰 K/U/lose va P0-3'ni jonli sheet'dan oladi, D hisobotini (`report.md`/`report.json`)
  bugungi raqamlar bilan QAYTA YOZADI va `push_reports` uni arxivga qayta push qiladi (yuqoridagi P0-3
  ogohlantirishi bilan bir xil).
- **Retention 40 kun** (`run.sh`): oy asosi (oldingi oyning oxirgi snapshot'i) oy oxirigacha o'chmasligi
  uchun. Bo'sh joyni tekshiring: `df -h /data` (yoki botda `/stt_status`) — bo'sh joy
  `10 × du -sh /data/snapshots/<bitta yaqin kun>` dan ko'p bo'lsin. Volume 1 GB, uning ~785 MB'ini STT
  modeli (`/data/models`) egallaydi; joy tugasa 09:00 fetch snapshot yozolmay to'xtaydi.
- **Kill switch:** Railway Variables'da `UNDIRUV_IZOHSIZ_OFF=1` → redeploy. P0-5 butunlay o'chadi
  (snapshot o'qilmaydi), 💰 blok, report.json, PDF va caption P0-5'siz holat bilan baytma-bayt bir xil.
  P0-3 kaliti (`UNDIRUV_CARRY_OFF`) alohida: P0-3 yoqiq bo'lsa, ko'chirilgan qatorni P0-3 O'SHA KUNI hukm
  qilsa (izohsiz ⚠️, o'tgan tab izohlagan ℹ️, «endi u yerda topilmadi») — P0-5 uni takrorlamaydi va X'ga
  P0-3 summasi bir marta qo'shiladi (Bosimov School, Tanho bitta ⚠️). P0-3 jim kunlari (qator asosga
  nisbatan joyida — masalan ustiga yangi hisob yozilgan) P0-5 o'z ⚠️/✅ ini beradi, shuning uchun X P0-3
  kalitidan qat'i nazar bir xil. Moslik nom + PM bo'yicha: shu nomli boshqa PM qatori yashirinmaydi.
  P0-3 o'chiq bo'lsa, P0-5 hammasini o'zi ko'rsatadi.
- **Oy oxiri (oxirgi 5 kun, keyingi oy tabi ochiq):** bo'shatilgan qator keyingi oy tabidagi juftiga
  «ko'chirilgan» (ℹ️, X'ga kirmaydi) deb faqat dalil bilan olinadi: muddati hali kelmagan qatorda —
  juft summasi aynan teng (Pruddy 30.09 → 05.10) yoki juft shu kuni shuncha o'sgan; muddati o'tgan qatorda —
  FAQAT juft shu kuni o'sgan (yoki yangi/keyingi tab kecha yo'q edi). Aks holda «⚠️ Izohsiz yo'qolish … ;
  «Undiruv noyabr(2026)» tabida «X» $N bor, lekin unga bu pul qo'shilmagan — ko'chirilgan bo'lsa holatini
  «Ega qarori» qiling» (keyingi tab odatda nusxa — mijozning navbatdagi hisobi).
- **/hisobot sheet tuzatilgandan keyin:** 💰 K/U/lose jonli, P0-5 esa bugungi 09:00 snapshot'idan. Ular farq
  qilsa — «ℹ️ Izohsiz yo'qolish: DD.MM 09:00 snapshot holati — …», X yorlig'ida «, 09:00 snapshot», caption'da
  « (09:00)», 2-foizda Lose snapshot'niki (bir pul L va X'da ikki marta sanalmaydi). Tuzatish ertangi
  09:00 da ✅ bo'ladi.
- **Bo'sh tab kuni:** snapshot'da joriy oy tabi butunlay bo'sh (`values: []`) yoki sarlavhasi o'qilmasa — kun
  ko'prik bilan o'tkaziladi («hamma qator o'chdi» emas).
- **Kalitdan qat'i nazar (shartsiz):** K − U = Q tekshiruvi ±$1 bilan va yangi matn «⚠️ Arifmetika mos
  emas, farq $N …» (09:30 jamlama va ega PDF'iga ham); kunlik PDF'da ham shu satr; «Jami»dan yuqoridagi
  PM'siz yig'indi qatorlari («Aktive Summary», «Ehtimoli aktive», «Jami:», faqat son/summa) loyiha deb
  sanalmaydi.
- **Faqat o'qiydigan CLI** (hech qanday fayl yozmaydi, P0-3 ro'yxatini ham muzlatmaydi). Bitta chaqiruv
  faqat o'sha KUN juftini (kecha → D) va D dagi ochiq ro'yxatni ko'rsatadi:
  ```bash
  cd /app && venv/bin/python undiruv_izohsiz.py --date 2026-10-17
  ```
- **Birinchi deploy:** avval Variables'da `UNDIRUV_IZOHSIZ_OFF=1` qo'yib deploy qiling. One-off shell'da
  CLI'ni oyning HAR KUNI uchun ishga tushiring (bitta sana boshqa kunlarni ko'rsatmaydi):
  ```bash
  cd /app && for d in $(seq -w 1 17); do echo "== 2026-10-$d"; venv/bin/python undiruv_izohsiz.py --date 2026-10-$d; done
  ```
  Qaysi kun nimani ko'rsatadi: 01.10 — 30.09→01.10 oktabr tabi o'zgarishlari; 02.10 — Icar24 (o'chirilgan
  bo'lsa «⚠️ Qator o'chirilgan», Lose $5 400 yozilgan bo'lsa faqat «ℹ️ Kelishilgan … Lose'ga −$5 400»);
  10.10 — o'chirilgan $0 qator ataylab HECH QACHON chiqmaydi (tekshiruv: o'sha kuni ⚠️ yo'q); 16.10 —
  Agromashtexnika ($500). Kutilgan ochiq ro'yxat (17.10): Trend snack $5 000, Agromashtexnika $500 (+ Bosimov —
  P0-3 satrida). Sheet'dan tuzatib bo'lmaydigan yolg'on hodisa chiqsa (juftlash/qayta nomlash xatosi —
  u oy oxirigacha har kuni takrorlanadi) — `UNDIRUV_IZOHSIZ_OFF=1` keyingi oyning 1-sanasigacha (zanjir
  yangidan boshlanadi) yoki kod tuzatilguncha qolsin; aks holda `UNDIRUV_IZOHSIZ_OFF`ni olib tashlang.
  Retention o'zgarishi (40 kun) iloji boricha tez deploy qilinsin — o'chgan snapshot qaytmaydi; xohlasangiz zaxira:
  `mkdir -p /data/keep && cp -r /data/snapshots/2026-09-2[5-9] /data/snapshots/2026-09-30 /data/snapshots/2026-10-0[12] /data/keep/`.
- **Ommaviy kun:** bir kunda ≥8 (va ≥25%) qator pul yo'qotsa (tab almashgan, ustun siljigan) —
  hodisalar baribir ochiladi va X'ga kiradi (yashirilmaydi), lekin bitta guruh ⚠️ satri bilan; tuzatilsa
  — bitta guruh ✅ satri.
- **Sheet egasi uchun qoida (AUDIT 5):** qator o'chirilmasin. Qator faqat Undirildi yoki Lose summa +
  holat («Puli yo'q»/«Pauza»/«Ega qarori») bilan yopiladi. Qisman to'lovda Summa aynan Undirildi'ga
  qo'shilgan summaga kamaysin (Tanho 30.09 — to'g'ri, Marvid 30.09 — noto'g'ri namuna). Faqat holat
  «Puli yo'q»/«Pauza» hodisani yopmaydi (pul Lose summa'ga yozilishi kerak); «Ega qarori» — yopadi.

## Eslatmalar / ma'lum cheklovlar

- Konteynerda `/dizayn` git-commit qilmaydi (theme'lar volume'da, git yo'q) —
  dizayn tarixи kerak bo'lsa Mac'dan `--code` bilan tortib olinadi (keyin hal qilamiz).
- Snapshot json tarixi (40 kun) Railway'da noldan yig'iladi — birinchi kun baseline,
  trend grafigi 7 kunda to'ladi. Dashboard'dagi Trend tabi (Google Sheets) to'liq qoladi.
- VPS varianti (deploy/deploy.sh, systemd) muqobil sifatida repo'da qoladi.
