#!/usr/bin/env python3
"""Production smoke test for AutoSEM.

Hits /health and 5 critical endpoints on the live deployment.
Exits 0 if all pass, 1 if any fail.

Usage:
    python scripts/smoke_test.py
    python scripts/smoke_test.py https://custom-url.example.com
"""

import sys
import time
import requests

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "https://auto-sem.replit.app"
TIMEOUT = 15

ENDPOINTS = [
    ("GET", "/health", 200, "status"),
    ("GET", "/version", 200, "version"),
    ("GET", "/api/v1/health/deep", 200, "status"),
    ("GET", "/api/v1/health/env-check", 200, "env_vars"),
    ("GET", "/api/v1/meta/status", 200, "connected"),
    ("GET", "/api/v1/dashboard/activity?limit=1", 200, None),
]


def run_smoke_tests():
    passed = 0
    failed = 0
    results = []

    print(f"\nAutoSEM Smoke Test — {BASE_URL}")
    print("=" * 60)

    for method, path, expected_status, expected_key in ENDPOINTS:
        url = f"{BASE_URL}{path}"
        start = time.time()

        try:
            if method == "GET":
                resp = requests.get(url, timeout=TIMEOUT)
            elif method == "POST":
                resp = requests.post(url, timeout=TIMEOUT)
            else:
                raise ValueError(f"Unknown method: {method}")

            elapsed_ms = int((time.time() - start) * 1000)
            status_ok = resp.status_code == expected_status

            key_ok = True
            if expected_key and status_ok:
                try:
                    data = resp.json()
                    key_ok = expected_key in data
                except Exception:
                    key_ok = False

            ok = status_ok and key_ok
            symbol = "PASS" if ok else "FAIL"

            if ok:
                passed += 1
            else:
                failed += 1

            detail = f"HTTP {resp.status_code}"
            if not status_ok:
                detail += f" (expected {expected_status})"
            if not key_ok:
                detail += f" (missing key: {expected_key})"

            results.append((symbol, method, path, elapsed_ms, detail))
            print(f"  [{symbol}] {method} {path} — {elapsed_ms}ms — {detail}")

        except requests.exceptions.Timeout:
            failed += 1
            results.append(("FAIL", method, path, TIMEOUT * 1000, "TIMEOUT"))
            print(f"  [FAIL] {method} {path} — TIMEOUT ({TIMEOUT}s)")

        except requests.exceptions.ConnectionError as e:
            failed += 1
            results.append(("FAIL", method, path, 0, f"CONNECTION_ERROR: {e}"))
            print(f"  [FAIL] {method} {path} — CONNECTION_ERROR")

        except Exception as e:
            failed += 1
            results.append(("FAIL", method, path, 0, str(e)))
            print(f"  [FAIL] {method} {path} — ERROR: {e}")

    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed, {passed + failed} total")

    if failed > 0:
        print("\nSMOKE TEST FAILED")
        return 1
    else:
        print("\nALL SMOKE TESTS PASSED")
        return 0


if __name__ == "__main__":
    sys.exit(run_smoke_tests())
