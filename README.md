# Polymarket Signal Dry-Run MVP

MVP ini untuk flow:
`chat signal -> parse -> resolve market -> rencana order`

## Status
- ✅ DRY RUN (tidak eksekusi order real)
- ✅ LIVE executor scaffold terpasang (manual confirmation + env creds wajib)

## 0) Setup Python venv

```bash
cd /root/.openclaw/workspace/polymarket_bot
python3 -m venv .venv
.venv/bin/pip install py-clob-client requests
```

## 1) Siapkan file signal
Bisa pakai contoh:

```bash
cp signals.example.txt signals.txt
```

Format yang didukung per baris:

- `MU vs BARCA | pick: BARCA`
- `ARSENAL VS MAN CITY - arsenal win`

## 2) Siapkan katalog market lokal

```bash
cp markets_catalog.example.json markets_catalog.json
```

Isi token id sesuai market Polymarket yang valid.

## 3) Jalankan dry-run

### Mode A — catalog lokal (stabil)
```bash
python3 signal_dryrun.py \
  --signals-file signals.txt \
  --catalog markets_catalog.json \
  --stake 20 \
  --max-spread 3 \
  --json-out plan.json
```

### Mode B — auto-resolve dari Gamma API
```bash
python3 signal_dryrun.py \
  --signals-file signals.txt \
  --auto-resolve \
  --scan-limit 1200 \
  --stake 20 \
  --max-spread 3 \
  --json-out plan.json
```

### Mode C — fetch langsung live league (contoh Ligue 1)
```bash
python3 signal_dryrun.py \
  --signals-file signals.txt \
  --live-league ligue-1 \
  --stake 20 \
  --max-spread 3 \
  --json-out plan.json
```

### Mode D — manual execution ticket (disarankan jika API geoblocked)
```bash
python3 signal_dryrun.py \
  --signals-file signals.txt \
  --live-league ligue-1 \
  --stake 1 \
  --manual-ticket-out tickets.txt \
  --max-slippage 2 \
  --json-out plan.json
```

Catatan mode C:
- Resolver ambil daftar pertandingan dari halaman `/sports/<league>/games`.
- Untuk market halftime Yes/No: `Yes = home leading`, `No = bukan home leading`.

Output terminal: ringkasan rencana order.
Output JSON: `plan.json`

## Kenapa pakai catalog lokal dulu?
Resolver event olahraga di Polymarket kadang butuh mapping detail outcome/token.
Untuk MVP aman, kita lock by mapping manual supaya ga salah market.

## Live execution (gunakan hati-hati)

Script: `execute_plan_live.py`

Contoh:
```bash
POLY_PK=0x... \
POLY_FUNDER=0x... \
.venv/bin/python execute_plan_live.py \
  --plan plan_live_test.json \
  --yes-live \
  --max-orders 2 \
  --out exec_result.json
```

Guard bawaan:
- wajib `--yes-live`
- hanya entry `READY_DRY_RUN` yang dieksekusi
- default limit BUY pakai best ask orderbook
- limit jumlah order (`--max-orders`)

## Chat bridge (YES/NO -> plan JSON)

Contoh dari pesan chat:
```bash
python3 chat_signal_bridge.py \
  --text "YES PSG 10" \
  --json-out exec_remote.json
```

Lalu kirim `exec_remote.json` ke runtime allowed untuk dieksekusi `execute_plan_live.py`.

## Remote-ready mode (untuk geoblock-safe flow)

Planner (di runtime yang kena geoblock):
```bash
python3 signal_dryrun.py \
  --signals-file signals.txt \
  --live-league ligue-1 \
  --stake 1 \
  --ready-status READY_REMOTE_EXEC \
  --idempotency-prefix tg-2984 \
  --json-out exec_remote.json
```

Executor (di runtime yang allowed):
```bash
POLY_PK=0x... POLY_FUNDER=0x... \
.venv/bin/python execute_plan_live.py \
  --plan exec_remote.json \
  --plan-ready-status READY_REMOTE_EXEC \
  --yes-live \
  --max-orders 2 \
  --out exec_result.json
```

## Auto-hook entrypoint (message -> plan -> optional executor)

Script: `telegram_signal_autohook.py`

Mode aman (planner only):
```bash
python3 telegram_signal_autohook.py \
  --text "YES PSG 10" \
  --market-question "PSG vs Toulouse" \
  --json-out exec_remote.json
```

Mode lanjut executor otomatis (hanya jika runtime memang allowed dan env live sudah siap):
```bash
python3 telegram_signal_autohook.py \
  --text "YES PSG 10" \
  --market-question "PSG vs Toulouse" \
  --json-out exec_remote.json \
  --execute \
  --executor-command '.venv/bin/python execute_plan_live.py --plan {plan} --plan-ready-status READY_REMOTE_EXEC --yes-live --max-orders 1 --out exec_result.json'
```

Catatan:
- Default behavior **tidak** live execute.
- Executor baru dipanggil kalau `--execute` + `--executor-command` diberikan eksplisit.
- Placeholder `{plan}` akan diganti path file plan hasil planner.

## Next step (hardening)
1. Tambah balance/allowance check sebelum submit order
2. Tambah spread guard real-time (best ask - best bid)
3. Tambah max price guard per signal
4. Tambah retry policy + idempotency key
