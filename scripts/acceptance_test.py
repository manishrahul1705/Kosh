#!/usr/bin/env python
"""Stage 1 acceptance test (section 37 of the spec), end to end.

Uses a throw-away SQLite DB and fixture data, the real CLI, a real uvicorn
server (started, queried, stopped, restarted) and pytest.

    python scripts/acceptance_test.py            # offline, deterministic
    python scripts/acceptance_test.py --live     # + one small live GeM run (3 pages)

Exit code 0 only if every executed check passed.
"""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "gem"
PY = sys.executable

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""), flush=True)
    return ok


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def cli(env: dict, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run([PY, "scripts/run_collection.py", *extra], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=600)


def parse_cli(out: str) -> dict[str, str]:
    data = {}
    for line in out.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            data[k.strip()] = v.strip()
    return data


def db_rows(db: Path, sql: str):
    con = sqlite3.connect(db)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


class Server:
    def __init__(self, env: dict, port: int):
        self.env, self.port, self.proc = env, port, None
        self.base = f"http://127.0.0.1:{port}"

    def start(self) -> bool:
        self.proc = subprocess.Popen(
            [PY, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(self.port)],
            cwd=ROOT, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for _ in range(60):
            try:
                if httpx.get(self.base + "/health", timeout=2).status_code in (200, 503):
                    return True
            except httpx.HTTPError:
                time.sleep(0.5)
        return False

    def stop(self) -> str:
        if self.proc is None:
            return ""
        self.proc.terminate()
        try:
            out, _ = self.proc.communicate(timeout=20)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            out, _ = self.proc.communicate()
        return out or ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="also attempt a small live GeM collection")
    ap.add_argument("--keep", action="store_true", help="keep the temp directory")
    args = ap.parse_args()

    work = Path(tempfile.mkdtemp(prefix="gem-acceptance-"))
    db = work / "acceptance.db"
    src = work / "source"
    shutil.copytree(FIX / "mock_abc" / "initial", src)

    env = {**os.environ,
           "DATABASE_URL": f"sqlite:///{db}",
           "COLLECTOR_MODE": "fixture",
           "FIXTURE_DIR": str(src),
           "LOCK_FILE": str(work / "collection.lock"),
           "DEBUG_DIR": str(work / "debug"),
           "SCHEDULER_ENABLED": "true",
           "COLLECT_ON_STARTUP": "false",
           "REQUEST_DELAY_SECONDS": "0",
           "LOG_LEVEL": "INFO"}
    print(f"Working directory: {work}\n")

    # TEST 1 — empty DB, run collection, tenders stored
    r = cli(env)
    out = parse_cli(r.stdout)
    n = db_rows(db, "select count(*) from tenders")[0][0] if db.exists() else 0
    check("TEST 1 collection stores tenders (empty DB)", r.returncode == 0 and out.get("New") == "3" and n == 3,
          f"exit={r.returncode} new={out.get('New')} rows={n}" + (f" stderr={r.stderr[-300:]}" if r.returncode else ""))

    # TEST 2 — run again, no duplicates
    r = cli(env)
    out = parse_cli(r.stdout)
    n = db_rows(db, "select count(*) from tenders")[0][0]
    d = db_rows(db, "select count(*) from (select bid_number from tenders group by bid_number having count(*)>1)")[0][0]
    check("TEST 2 second run creates no duplicates", out.get("New") == "0" and out.get("Unchanged") == "3" and n == 3 and d == 0,
          f"new={out.get('New')} unchanged={out.get('Unchanged')} rows={n}")

    # TEST 3 — controlled fixture with changed closing date
    shutil.copy(FIX / "mock_abc" / "b_closing_changed" / "page_1.json", src / "page_1.json")
    r = cli(env)
    out = parse_cli(r.stdout)
    check("TEST 3 changed closing date detected as update", out.get("Updated") == "1" and out.get("Unchanged") == "2",
          f"updated={out.get('Updated')} unchanged={out.get('Unchanged')}")

    # TEST 4 — tender_changes row
    rows = db_rows(db, "select field_name, old_value, new_value from tender_changes")
    check("TEST 4 tender_changes holds old/new closing date",
          rows == [("bid_end_at", "2026-10-10T09:30:00Z", "2026-10-12T12:30:00Z")], str(rows))

    # TESTS 5-10 — live server
    port = free_port()
    srv = Server(env, port)
    started = srv.start()
    if not check("server starts (uvicorn app.main:app)", started):
        print(srv.stop()[-2000:])
        return finish(work, args.keep)
    try:
        h = httpx.get(srv.base + "/health").json()
        check("TEST 5 /health", h.get("status") == "healthy" and h.get("database") == "connected", str(h))
        t = httpx.get(srv.base + "/api/tenders", params={"page": 1, "page_size": 2}).json()
        check("TEST 6 /api/tenders", t.get("total") == 3 and len(t.get("items", [])) == 2, f"total={t.get('total')}")
        nw = httpx.get(srv.base + "/api/tenders/new", params={"hours": 24}).json()
        check("TEST 7 /api/tenders/new", nw.get("total") == 3, f"total={nw.get('total')}")
        st = httpx.get(srv.base + "/api/stats").json()
        check("TEST 8 /api/stats", st.get("total_tenders") == 3 and st.get("last_collection_status") == "SUCCESS", str(st))
        mr = httpx.post(srv.base + "/api/collection/run", timeout=120)
        mb = mr.json()
        check("TEST 9 POST /api/collection/run", mr.status_code == 200 and mb.get("status") == "SUCCESS"
              and mb.get("bids_seen") == 3 and mb.get("trigger_type") == "manual", str(mb))
        check("TEST 10 scheduler initialised", h.get("scheduler") == "running" and h.get("next_scheduled_run") is not None,
              f"scheduler={h.get('scheduler')} next={h.get('next_scheduled_run')}")
    finally:
        log = srv.stop()
    check("server shut down cleanly (scheduler_stopped logged)", "scheduler_stopped" in log)

    # TEST 11 — pytest
    p = subprocess.run([PY, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=ROOT,
                       capture_output=True, text=True, timeout=900)
    tail = (p.stdout.strip().splitlines() or ["no output"])[-1]
    check("TEST 11 pytest", p.returncode == 0, tail)

    # TEST 12 — restart, data persists
    srv = Server(env, free_port())
    ok = srv.start()
    try:
        t = httpx.get(srv.base + "/api/tenders").json() if ok else {}
        runs = httpx.get(srv.base + "/api/collection/runs").json() if ok else []
        check("TEST 12 records persist after restart", ok and t.get("total") == 3 and len(runs) == 4,
              f"tenders={t.get('total')} runs={len(runs)}")
    finally:
        srv.stop()

    if args.live:
        live_env = {**env, "COLLECTOR_MODE": "auto", "MAX_PAGES_PER_RUN": "3", "REQUEST_DELAY_SECONDS": "2",
                    "DATABASE_URL": f"sqlite:///{work / 'live.db'}", "SAVE_DEBUG_SNAPSHOTS": "true"}
        r = cli(live_env)
        out = parse_cli(r.stdout)
        check("LIVE small GeM collection (3 pages)", r.returncode == 0 and int(out.get("Bids seen", "0") or 0) > 0,
              f"status={out.get('Status')} seen={out.get('Bids seen')} details={out.get('Details', '')[:300]}")

    return finish(work, args.keep)


def finish(work: Path, keep: bool) -> int:
    passed = sum(ok for _, ok, _ in results)
    print(f"\n{passed}/{len(results)} checks passed")
    if not keep:
        shutil.rmtree(work, ignore_errors=True)
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
