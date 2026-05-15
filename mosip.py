import asyncio
import json
import os
from pathlib import Path
from typing import Optional
from pydantic import BaseModel

from dynaconf import Dynaconf
from mosip_auth_sdk import MOSIPAuthenticator
from mosip_auth_sdk.models import DemographicsModel

_CONFIG_PATH = Path(__file__).resolve().parent / ".mosip_keys" / "config.toml"
_authenticator: Optional[MOSIPAuthenticator] = None
_config_error: Optional[str] = None


def _get_authenticator() -> Optional[MOSIPAuthenticator]:
    global _authenticator, _config_error
    if _authenticator is not None:
        return _authenticator
    if _config_error is not None:
        return None
    try:
        if not _CONFIG_PATH.exists():
            _config_error = f"MOSIP config not found at {_CONFIG_PATH}"
            return None
        config = Dynaconf(
            settings_files=[str(_CONFIG_PATH)],
            load_dotenv=True,
            environments=False,
        )
        _authenticator = MOSIPAuthenticator(config=config)
        return _authenticator
    except Exception as e:
        _config_error = f"MOSIP init failed: {e}"
        return None

class MOSIPVerificationResult(BaseModel):
    verified: bool
    individual_id: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    transaction_id: Optional[str] = None
    message: str = ""

# ... (parse_philsys_qr function remains the same) ...

def parse_philsys_qr(raw: str) -> Optional[dict]:
    try:
        data = json.loads(raw)
        if "uin" in data:
            name_parts = data.get("name", "").split(None, 1)
            return {
                "individual_id": data["uin"],
                "first_name": name_parts[0] if name_parts else "",
                "last_name": name_parts[1] if len(name_parts) > 1 else "",
                "dob": data.get("dob", ""),
                "name": data.get("name", ""),
            }
        if "individualId" in data:
            name_parts = data.get("name", "").split(None, 1)
            return {
                "individual_id": data["individualId"],
                "first_name": name_parts[0] if name_parts else "",
                "last_name": name_parts[1] if len(name_parts) > 1 else "",
                "dob": data.get("dob", ""),
                "name": data.get("name", ""),
            }
    except (json.JSONDecodeError, TypeError, KeyError):
        pass
    return None

def _do_mosip_auth(parsed: dict) -> MOSIPVerificationResult:
    auth = _get_authenticator()
    if auth is None:
        return MOSIPVerificationResult(
            verified=False,
            individual_id=parsed["individual_id"],
            first_name=parsed["first_name"],
            last_name=parsed["last_name"],
            message=f"MOSIP not configured ({_config_error}).",
        )

    demographics_data = DemographicsModel(
        dob=parsed["dob"]
    )

    response = auth.auth(
        individual_id=parsed["individual_id"],
        individual_id_type="UIN",
        demographic_data=demographics_data,
        consent=True,
    )

    if not response.text:
        return MOSIPVerificationResult(
            verified=False,
            message="MOSIP server returned empty response.",
        )

    response_body = response.json()
    auth_response = response_body.get("response", {})
    auth_status = auth_response.get("authStatus", False)
    transaction_id = response_body.get("transactionID", "")

    # We still keep the names for the UI, but we only verified the DOB
    return MOSIPVerificationResult(
        verified=auth_status,
        individual_id=parsed["individual_id"],
        first_name=parsed["first_name"],
        last_name=parsed["last_name"],
        transaction_id=transaction_id,
        message="✅ Verified via DOB" if auth_status else "❌ Verification failed.",
    )

async def verify_qr(qr_data: str) -> MOSIPVerificationResult:
    parsed = parse_philsys_qr(qr_data)
    if parsed is None:
        return MOSIPVerificationResult(
            verified=False,
            message="Invalid QR code format.",
        )
    if os.environ.get("MOSIP_SKIP_VERIFICATION") == "1":
        return MOSIPVerificationResult(
            verified=True,
            individual_id=parsed["individual_id"],
            first_name=parsed["first_name"],
            last_name=parsed["last_name"],
            message="MOSIP verification skipped.",
        )
    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: _do_mosip_auth(parsed))
    except Exception as e:
        return MOSIPVerificationResult(
            verified=False,
            message=f"MOSIP error: {str(e)}",
        )