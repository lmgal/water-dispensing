"""Verify pre-decoded PhilSys QR payloads against the MOSIP testbed.

Reads one JSON payload per line from the file given as argv[1] (or stdin)
and calls mosip.verify_qr on each. Pre-decoding avoids needing pyzbar on
the host that has the WireGuard tunnel up.
"""
import asyncio
import json
import sys

from mosip import verify_qr


async def main() -> int:
    src = open(sys.argv[1]) if len(sys.argv) > 1 else sys.stdin
    payloads = [line.strip() for line in src if line.strip()]
    if not payloads:
        print("no payloads on stdin/file", file=sys.stderr)
        return 1

    results = []
    for raw in payloads:
        parsed = json.loads(raw)
        label = parsed.get("file") or parsed.get("name") or parsed.get("uin")
        print(f"\n=== {label} ({parsed.get('name')}, UIN {parsed.get('uin')}, DOB {parsed.get('dob')}) ===")
        res = await verify_qr(raw)
        print(f"  verified       : {res.verified}")
        print(f"  transaction_id : {res.transaction_id}")
        print(f"  message        : {res.message}")
        results.append((label, res.verified))

    print("\n--- Summary ---")
    for label, ok in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    return 0 if all(ok for _, ok in results) else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
