"""Rebuild the Kosh demonstration database to the exact start state for testing and evaluation."""
from __future__ import annotations
import argparse, os, sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database.session import run_migrations, build_engine, build_session_factory
from scripts.kosh_generate_demo import generate
from scripts.kosh_seed_demo import seed


def reset_demo(database_url: str = "sqlite:///./kosh_work.db", seed_num: int = 42, as_of: date = date(2026, 10, 13)) -> None:
    data_dir = ROOT / "demo_data"
    storage_dir = ROOT / "private_storage"

    print(f"[*] Resetting demo database to canonical start state...")
    print(f"    - Database URL : {database_url}")
    print(f"    - As-of date   : {as_of.isoformat()}")
    print(f"    - Random seed  : {seed_num}")

    # If local SQLite file, remove previous file for a clean rebuild
    if database_url.startswith("sqlite:///"):
        rel_path = database_url.replace("sqlite:///", "")
        if rel_path != ":memory:":
            db_file = Path(rel_path)
            if not db_file.is_absolute():
                db_file = ROOT / db_file
            if db_file.exists():
                try:
                    db_file.unlink()
                    print(f"    - Cleared existing database file: {db_file}")
                except Exception as exc:
                    print(f"    - Warning: could not unlink {db_file}: {exc}")

    # 1. Run migrations to head
    print("[1/3] Applying schema migrations...")
    run_migrations(database_url)

    # 2. Generate demo data
    print("[2/3] Generating deterministic demo datasets (sales, purchases, bank statement, PDFs)...")
    generate(seed=seed_num, out=data_dir, as_of=as_of)

    # 3. Seed database
    print("[3/3] Ingesting and processing demo documents via private store...")
    seed(database_url=database_url, data_dir=data_dir, storage=storage_dir)

    print("\n====================================================================")
    print("SUCCESS: Kosh demo environment reset complete!")
    print("====================================================================")
    print("Demo seller : Meenakshi Precision Components")
    print("Start state : 18 ingested documents, 2 poisoned documents quarantined in REVIEW,")
    print("              0 executed plans, 0 settled actions.")
    print("\nHOW TO RUN:")
    print("  1. Start backend  : uvicorn app.main:app --host 127.0.0.1 --port 8010")
    print("  2. Start frontend : cd frontend && npm run dev -- --host 127.0.0.1 --port 5180")
    print("  3. Log in         : Open http://127.0.0.1:5180/login and use Dev Sign-In with any email")
    print("  4. Walkthrough    : Follow the 5-minute click path in docs/kosh/demo_walkthrough.md")
    print("====================================================================\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Reset Kosh demo database to initial state.")
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL", "sqlite:///./kosh_work.db"))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--as-of", type=date.fromisoformat, default=date(2026, 10, 13))
    args = parser.parse_args()
    reset_demo(database_url=args.database_url, seed_num=args.seed, as_of=args.as_of)
