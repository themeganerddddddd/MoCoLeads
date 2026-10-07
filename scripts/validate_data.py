from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.validation import validate_records


def main() -> None:
    data_dir = ROOT / "data"
    contracts = json.loads((data_dir / "contracts.json").read_text(encoding="utf-8"))
    latest = json.loads((data_dir / "latest.json").read_text(encoding="utf-8"))
    metadata = json.loads((data_dir / "metadata.json").read_text(encoding="utf-8"))
    validate_records(contracts)
    validate_records(latest)
    if metadata.get("record_count") != len(contracts):
        raise RuntimeError("metadata record_count does not match contracts.json")
    if latest != contracts[:25]:
        raise RuntimeError("latest.json is not the newest 25 records from contracts.json")
    print(f"Validated {len(contracts)} contracts and {len(latest)} latest records.")


if __name__ == "__main__":
    main()
