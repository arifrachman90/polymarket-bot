# Full-Auto YES/NO Trading Spec (Geoblock-Safe)

## Goal
User hanya kirim sinyal chat `YES` / `NO`, sistem otomatis:
1) resolve market aktif,
2) hitung size,
3) kirim order dari runtime yang **allowed**,
4) kirim status hasil ke chat.

## Constraint Utama
- Runtime ini kena `CLOB 403 geoblock` untuk live order.
- Jadi planner boleh jalan di sini, **executor live wajib dipindah** ke runtime allowed.

## Arsitektur

### A. Planner (current runtime)
Input: pesan chat (YES/NO + optional konteks)
Output: `exec_*.json` berisi plan siap eksekusi

Tugas planner:
- Parse sinyal (`YES`/`NO`)
- Resolve target market + token_id
- Isi guardrail:
  - stake_usd default
  - max price/slippage
  - max orders
  - TTL/expiry singkat
- Status hasil planning: `READY_REMOTE_EXEC`

### B. Executor (allowed runtime)
Input: `exec_*.json`
Output: hasil posting order (`POSTED/FILLED/ERROR`)

Tugas executor:
- Validasi file plan + status `READY_REMOTE_EXEC`
- Ambil best ask / apply price guard
- Submit order via CLOB signed auth
- Simpan log + return summary

### C. Reporter
- Push ringkas ke chat:
  - market
  - side (YES/NO)
  - price
  - size
  - order_id/error

## Sinyal Chat (minimal)
- `YES`
- `NO`

## Sinyal Chat (opsional, disarankan)
- `YES PSG 10`
- `NO Arsenal 5`

Jika user hanya kirim `YES/NO`, resolver pakai:
1) last active ticket,
2) market terbaru yang di-track,
3) fallback minta klarifikasi (sekali, singkat).

## Risk Guards (wajib)
- Max stake per signal (default kecil)
- Max daily exposure
- Max slippage (mis. 2%)
- Reject jika orderbook tipis / spread lebar
- Cooldown anti double-submit (idempotency key)

## Error Policy
- `403/geoblock`: tandai `REROUTE_REQUIRED`, jangan retry lokal
- `429/503/timeout`: retry exponential backoff terbatas
- Jika partial failure: lapor detail per order

## File Contract (planner -> executor)
Contoh minimum:
```json
{
  "version": 1,
  "created_at": "2026-03-23T09:00:00Z",
  "source": "telegram:557166755",
  "status": "READY_REMOTE_EXEC",
  "signals": [
    {
      "side": "YES",
      "market_slug": "example-market",
      "token_id": "12345",
      "stake_usd": 10,
      "max_slippage_pct": 2,
      "idempotency_key": "tg-2984-1"
    }
  ]
}
```

## Immediate Next Steps
1. Lock final signal grammar (YES/NO + optional market + optional stake).
2. Update planner output status from `READY_DRY_RUN` -> `READY_REMOTE_EXEC` (mode remote).
3. Add executor mode `--plan-ready-remote` untuk allowed runtime.
4. Add reporter template ke chat (single concise message).
5. Test end-to-end pakai size kecil.

## Done Criteria
- User kirim 1 pesan (`YES`/`NO`)
- Sistem auto place order tanpa klik manual
- Hasil order balik ke chat < 10 detik (normal path)
