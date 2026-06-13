"""Fetch and pretty-print each dashboard endpoint for shape confirmation."""
import json
import sys

import httpx

BASE = "http://127.0.0.1:8011"


def show(label: str, path: str) -> None:
    print(f"\n===== {label} =====")
    r = httpx.get(BASE + path, timeout=20)
    print(json.dumps(r.json(), indent=2))


def main() -> None:
    show("GET /api/summary", "/api/summary")
    show("GET /api/exposure", "/api/exposure")
    show("GET /api/positions?status=open", "/api/positions?status=open")
    show("GET /api/positions?status=resolved", "/api/positions?status=resolved")

    # full audit for the first open position's decision_id
    positions = httpx.get(BASE + "/api/positions?status=open", timeout=20).json()
    if positions:
        did = positions[0]["decision_id"]
        show(f"GET /api/decisions/{did}", f"/api/decisions/{did}")


if __name__ == "__main__":
    sys.exit(main())
