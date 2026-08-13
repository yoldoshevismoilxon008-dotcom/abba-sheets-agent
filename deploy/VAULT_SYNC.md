# Vault → Bilim bazasi sinxroni (B2.1) — o'rnatish

Obsidian "claude brain" vaultidagi qaydlar KB'ga tushib, har Q&A savolida
avtomatik kontekst bo'lib ishlatiladi. **Faqat O'QISH** yo'nalishi.

```
~/claude-brain ──(Mac launchd, har 10daq)──▶ GitHub private repo
                    brain-push.sh                    │
                                                     ▼
   KB (knowledge.db) ◀──(Railway, har 10daq)── vault_sync.py (clone/pull)
        │                                       source="vault", meta_min_chars=1500
        ▼
   Q&A: context_for → {{KNOWLEDGE}} (manba: [[nisbiy/yo'l]] wiki-link)
```

Manba = **`~/claude-brain`** (46 jonli .md, git repo). Obsidian ilovasida ham
shu papka vault sifatida ochiladi → javobdagi `[[...]]` linklar bosib ochiladi.

---

## Bir martalik o'rnatish (ega bajaradi)

### 1. Private repo yaratish
GitHub'da (`yoldoshevismoilxon008-dotcom`) **bo'sh** private repo: `claude-brain`.
⚠️ README/`.gitignore` bilan **auto-init QILMANG** (aks holda birinchi push rad etiladi).

### 2. `.kbignore` ni sozlash (BIRINCHI PUSH'DAN OLDIN!)
`~/claude-brain/.kbignore` allaqachon yaratilgan (shablon). Maxfiy papkalarni
qo'shing, keyin `__UNCONFIGURED__` qatorini **o'chiring**:
```
odam/                 # misol — maxfiy papkalaringizni yozing
kunlik/shaxsiy/
```
> `.git`, `.obsidian`, `.trash`, `.DS_Store` allaqachon avtomatik chetlab o'tiladi.
> `.kbignore`'ni push'dan OLDIN to'g'rilash muhim — shunda maxfiy papka git
> tarixiga umuman kirmaydi.
> ⚠️ Maxfiy narsa **bir marta push bo'lib ketgan** bo'lsa, keyin `.kbignore`'ga
> qo'shish YETARLI EMAS — u faqat kelgusi push'dan chiqaradi, GitHub **tarixida
> qoladi**. Bunday holda `git rm --cached` ham tarixni tozalamaydi; sirni
> (token/parol) **ROTATSIYA** qilish shart.

### 3. Vault remote + birinchi push (qo'lda, auth tekshirish uchun)
```bash
git -C ~/claude-brain remote add origin git@github.com:yoldoshevismoilxon008-dotcom/claude-brain.git
git -C ~/claude-brain add -A
git -C ~/claude-brain commit -m "vault: dastlabki sinxron"
git -C ~/claude-brain push -u origin main
```

### 4. Railway o'qish uchun token
GitHub → Settings → Developer settings → **Fine-grained PAT**:
- Repository access: **faqat** `claude-brain`
- Permissions: **Contents → Read-only**
- Nom: `GH_TOKEN_VAULT`

### 5. Railway env
```
VAULT_REPO      = yoldoshevismoilxon008-dotcom/claude-brain
GH_TOKEN_VAULT  = github_pat_...   (4-qadamdagi token)
```
Env bo'lmasa vault_sync `disabled` — bot normal ishlayveradi.

### 6. Mac launchd (har 10daq push)
```bash
cp ~/abba-sheets-agent/launchd/com.abba.brain-push.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.abba.brain-push.plist
# Tekshirish:
cat ~/abba-sheets-agent/data/logs/brain-push-status.txt
```

### 7. Sinxronni "qurollantirish"
`.kbignore`'dan `__UNCONFIGURED__` o'chirilgach (2-qadam), birinchi to'liq sinxron
keyingi 10 daqiqada yoki Telegram'da `/vault_sync` bilan darhol ishga tushadi.

---

## Taxminiy narx (birinchi to'liq ingest)

- **~30–32 fayl** (>1500 belgi) Claude metadata chaqiradi, `effort=low`, har biri
  ≤6000 belgi + qisqa prompt. **14 fayl** (≤1500 belgi) — Claude'siz (light meta), $0.
- Railway Max-obuna OAuth (`CLAUDE_CODE_OAUTH_TOKEN`) → **API $ xarajat yo'q**,
  obuna usage'i. `content_hash` tufayli **bir martalik** — keyin faqat o'zgargan fayl.
- (Agar server'da `ANTHROPIC_API_KEY` bo'lsa: bir martalik ~50–65K input / ~3K
  output token, low effort.)
- **Steady-state:** har 10daq faqat o'zgargan fayl(lar) — odatda kuniga 1–3 (kunlik
  yozuv, holat.md) → deyarli hech narsa.

---

## Buyruqlar / holat

- `/vault_sync` — qo'lda majburiy sinxron (fonda, natijani xabar qiladi)
- `/vault_stat` — vault hujjat/chunk soni, oxirgi muvaffaqiyatli sinxron, o'tkazib
  yuborilgan papkalar
- Mac status: `data/logs/brain-push-status.txt` (heartbeat), `brain-push.log` (push/xato)

## Xatti-harakat kafolatlari
- **KB yiqilsa Q&A davom etadi**: vault_sync.run() hech qachon raise qilmaydi;
  supervisor job try/except. Sinxron xatosi → faqat log + egaga **kuniga bir marta** TG.
- **Maxfiylik**: `.kbignore` yo'q bo'lsa Mac push va Railway ingest **to'xtaydi**;
  `__UNCONFIGURED__` turgan ekan sinxron o'chiq.
- **Log shishmasin**: o'zgarish bo'lmagan run'lar faqat status faylni yangilaydi.

---

## B2.2 — Chat arxivi (suhbatni vault + KB'ga past vazn bilan)

Bot har javobdan keyin suhbatni `DATA/chat/YYYY-MM-DD.md` ga yozadi. Oqim:

```
bot javob → DATA/chat/*.md ──(push_chat, 10daq)──▶ REPORTS_REPO/chat/
                                                          │
   ~/claude-brain/chat/ ◀──(reports-pull, 10daq)─────────┘   (vault ILDIZI)
        │
        └─(brain-push)─▶ bilim repo ─(vault_sync)─▶ KB (source="chat", past vazn)
```

- **Faqat vault_sync ingest qiladi** — bot HECH QACHON `kb.ingest` chaqirmaydi (ikki marta tushmasin).
- **Past vazn:** chat qidiruvda ×0.6 jarima (`KB_CHAT_PENALTY`), kontekstga ko'pi 2 chat bo'lagi,
  faqat vault/doc'dan keyin; «O'tgan suhbat (tasdiqlanmagan)» sarlavhasi ostida.
- **90 kun:** faqat oxirgi 90 kunlik chat KB'da; eskisi vault'da o'qish uchun qoladi, KB'dan
  **arxivlanadi** (ataylab). Chat metadata uchun Claude **chaqirilmaydi** (barqaror sarlavha).

### ⚠️ Maxfiylik — REPORTS_REPO endi chat'ni ham tashiydi
Chat arxivida botga yozgan **hamma narsa** bo'ladi. `abba-hisobotlar` **PRIVATE** turishi SHART
(2026-08-12 da public'dan private'ga o'zgartirilgan). `.kbignore` ga `chat/` QO'SHILMASIN.

### Reports-pull intervalini yangilash (3600 → 600, chat tez tortilishi uchun)
```bash
cp ~/abba-sheets-agent/launchd/com.abba.reports-pull.plist ~/Library/LaunchAgents/
launchctl unload ~/Library/LaunchAgents/com.abba.reports-pull.plist
launchctl load  ~/Library/LaunchAgents/com.abba.reports-pull.plist
```
`vault_pull.sh` allaqachon `chat/` → `~/claude-brain/chat/` tortadi (hisobotlar ichida emas).
Railway'da qo'shimcha env shart emas — `push_chat` mavjud `REPORTS_REPO`+`GH_TOKEN_REPORTS`dan foydalanadi.

### Kechikish
Uchidan-uchiga ~30–40 daqiqa (bot→push_chat→reports-pull→brain-push→vault_sync). Chat *kelgusi*
savollarga kontekst — darhol emas.
