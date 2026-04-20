"""
Simulated MOSIP/PhilSys ID verification.

Reference: https://github.com/hrdungca2/cs145-iot-cup-sample-code
Real MOSIP uses:
  - Base: https://api-internal.pdec.mosip.net
  - Auth: /idauthentication/v1 (OTP-based or demographic)
  - KYC:  /idauthentication/v1/kyc (demographic + consent)
  - OTP:  /idauthentication/v1/otp (generate OTP via email/phone)

This module simulates the MOSIP testbed verification flow for development.
In production, replace with actual mosip-auth-sdk calls.
"""

import asyncio
import json
from typing import Optional

from pydantic import BaseModel

from config import MOSIP_SIMULATION_DELAY

# Simulated MOSIP testbed endpoint (not called, just for reference)
MOSIP_BASE_URL = "https://api-internal.pdec.mosip.net"
MOSIP_AUTH_ENDPOINT = f"{MOSIP_BASE_URL}/idauthentication/v1"


class MOSIPVerificationResult(BaseModel):
    verified: bool
    individual_id: Optional[str] = None  # UIN / PhilSys ID
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    transaction_id: Optional[str] = None
    message: str = ""


def parse_philsys_qr(raw: str) -> Optional[dict]:
    """
    Extract fields from a PhilSys QR code payload.

    Expected QR JSON format (as scanned by GM861S):
    {
        "individualId": "1234567890",   // UIN
        "name": "JUAN DELA CRUZ",
        "dob": "1990-05-15",
        "gender": "M",
        "address": "Brgy. Sample, Manila"
    }

    Also accepts simplified format:
    {
        "id": "PSN-2024-00001",
        "firstName": "Juan",
        "lastName": "Dela Cruz"
    }
    """
    try:
        data = json.loads(raw)

        # MOSIP/PhilSys standard format (individualId + name)
        if "individualId" in data:
            name_parts = data.get("name", "").split(None, 1)
            return {
                "individual_id": data["individualId"],
                "first_name": name_parts[0] if name_parts else "",
                "last_name": name_parts[1] if len(name_parts) > 1 else "",
            }

        # Simplified format (id + firstName + lastName)
        if "id" in data and "firstName" in data and "lastName" in data:
            return {
                "individual_id": data["id"],
                "first_name": data["firstName"],
                "last_name": data["lastName"],
            }
    except (json.JSONDecodeError, TypeError, KeyError):
        pass
    return None


async def verify_qr(qr_data: str) -> MOSIPVerificationResult:
    """
    Simulate MOSIP testbed QR verification.

    In production this would:
    1. Parse QR to extract individualId
    2. Call MOSIP /idauthentication/v1 with demographic data
    3. Verify RS256 signed response
    4. Return identity confirmation

    For the testbed, we simulate the network delay and
    validate the QR format locally.
    """
    # Simulate MOSIP API round-trip delay
    await asyncio.sleep(MOSIP_SIMULATION_DELAY)

    parsed = parse_philsys_qr(qr_data)
    if parsed is None:
        return MOSIPVerificationResult(
            verified=False,
            message="Invalid QR code format. Expected PhilSys National ID QR.",
        )

    # Simulate successful MOSIP demographic auth response
    import hashlib
    txn_id = hashlib.sha256(
        f"{parsed['individual_id']}:{asyncio.get_event_loop().time()}".encode()
    ).hexdigest()[:16]

    return MOSIPVerificationResult(
        verified=True,
        individual_id=parsed["individual_id"],
        first_name=parsed["first_name"],
        last_name=parsed["last_name"],
        transaction_id=txn_id,
        message="Identity verified via MOSIP testbed (demographic auth).",
    )
