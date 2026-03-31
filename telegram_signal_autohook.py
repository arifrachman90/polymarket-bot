#!/usr/bin/env python3
"""
Telegram-like message -> plan JSON -> optional executor command.

Tujuan:
- Satu entrypoint untuk flow auto-hook.
- Aman by default: hanya bikin plan, tidak live execute kecuali diminta eksplisit.

Contoh:
  python3 telegram_signal_autohook.py \
    --text "YES PSG 10" \
    --market-question "PSG vs Toulouse" \
    --json-out exec_remote.json

  python3 telegram_signal_autohook.py \
    --text "YES PSG 10" \
    --market-question "PSG vs Toulouse" \
    --json-out exec_remote.json \
    --execute \
    --executor-command '.venv/bin/python execute_plan_live.py --plan {plan} --plan-ready-status READY_REMOTE_EXEC --yes-live --max-orders 1 --out exec_result.json'
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict


HERE = Path(__file__).resolve().parent
BRIDGE = HERE / "chat_signal_bridge.py"


def run_cmd(argv: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, cwd=str(cwd), text=True, capture_output=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="Auto-hook message -> plan -> optional executor")
    ap.add_argument("--text", required=True, help='Contoh: "YES PSG 10"')
    ap.add_argument("--market-question", default="", help='Konteks market, contoh: "PSG vs Toulouse"')
    ap.add_argument("--default-stake", type=float, default=1.0)
    ap.add_argument("--scan-limit", type=int, default=1200)
    ap.add_argument("--idempotency-prefix", default="tg")
    ap.add_argument("--json-out", required=True)
    ap.add_argument("--execute", action="store_true", help="Lanjut panggil executor-command setelah plan jadi")
    ap.add_argument(
        "--executor-command",
        default="",
        help="Command executor. Boleh pakai placeholder {plan}. Tidak dijalankan kecuali --execute.",
    )
    args = ap.parse_args()

    out_path = Path(args.json_out)
    if not out_path.is_absolute():
        out_path = (Path.cwd() / out_path).resolve()

    bridge_cmd = [
        sys.executable,
        str(BRIDGE),
        "--text",
        args.text,
        "--default-stake",
        str(args.default_stake),
        "--scan-limit",
        str(args.scan_limit),
        "--idempotency-prefix",
        args.idempotency_prefix,
        "--json-out",
        str(out_path),
    ]
    if args.market_question:
        bridge_cmd += ["--market-question", args.market_question]

    bridge = run_cmd(bridge_cmd, cwd=HERE)
    if bridge.returncode != 0:
        raise SystemExit(
            json.dumps(
                {
                    "ok": False,
                    "stage": "planning",
                    "returncode": bridge.returncode,
                    "stdout": bridge.stdout,
                    "stderr": bridge.stderr,
                },
                ensure_ascii=False,
                indent=2,
            )
        )

    payload: Dict[str, Any] = json.loads(out_path.read_text(encoding="utf-8"))
    result: Dict[str, Any] = {
        "ok": True,
        "stage": "planned",
        "plan_path": str(out_path),
        "plan_status": payload.get("status"),
        "bridge_stdout": bridge.stdout.strip(),
        "plans": len(payload.get("plans") or []),
        "executed": False,
    }

    if args.execute:
        if not args.executor_command.strip():
            raise SystemExit("--execute but --executor-command kosong")
        cmd = args.executor_command.replace("{plan}", shlex.quote(str(out_path)))
        exec_proc = subprocess.run(cmd, cwd=str(HERE), text=True, capture_output=True, shell=True)
        result.update(
            {
                "executed": True,
                "executor_returncode": exec_proc.returncode,
                "executor_stdout": exec_proc.stdout.strip(),
                "executor_stderr": exec_proc.stderr.strip(),
                "stage": "executed" if exec_proc.returncode == 0 else "executor_error",
                "ok": exec_proc.returncode == 0,
            }
        )

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
