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
    if seed_num != 42 or as_of != date(2026, 10, 13):
        # Preserve custom input generation for local experiments. The judge
        # workspace always uses the canonical full seed through the default path.
        if not database_url.startswith("sqlite:///"):
            raise ValueError("Reset requires a local SQLite file")
        path=Path(database_url[len("sqlite:///"):])
        if not path.is_absolute():path=ROOT/path
        path=path.resolve()
        if not path.is_relative_to(ROOT):raise ValueError("Reset must stay inside the repository workspace")
        for target in (path,Path(str(path)+"-wal"),Path(str(path)+"-shm")):
            if target.is_file():target.unlink()
        run_migrations(database_url)
        generate(seed=seed_num,out=ROOT/"demo_data",as_of=as_of)
        seed(database_url,ROOT/"demo_data",ROOT/"private_storage")
        return
    from scripts.kosh_setup import setup
    result = setup(database_url, reset=True)
    print(f"Business workspace restored for seller {result['seller_id']}.")
    print("Start the backend on 8010 and frontend on 5180; use local sign-in with any email.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Reset Kosh demo database to initial state.")
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL", "sqlite:///./kosh_work.db"))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--as-of", type=date.fromisoformat, default=date(2026, 10, 13))
    args = parser.parse_args()
    reset_demo(database_url=args.database_url, seed_num=args.seed, as_of=args.as_of)
