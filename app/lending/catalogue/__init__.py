"""Versioned financing catalogue loader."""
from json import loads
from pathlib import Path

def load_catalogue():
    return [loads(path.read_text(encoding="utf-8-sig")) for path in sorted(Path(__file__).parent.glob("*.json"))]
