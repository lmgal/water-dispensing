import asyncio
import json
import hashlib
from typing import Optional
from pydantic import BaseModel

# Load real MOSIP SDK
from dynaconf import Dynaconf
from mosip_auth_sdk import MOSIPAuthenticator
from mosip_auth_sdk.models import DemographicsModel, IdentityInfo

# --- UPDATED PATH HERE ---
config = Dynaconf(
    settings_files=[".mosip_keys/config.toml"], 
    load_dotenv=True,
    environments=False
)
authenticator = MOSIPAuthenticator(config=config)

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
    """Real MOSIP SDK call — runs in thread pool."""
    demographics_data = DemographicsModel(
        dob=parsed["dob"],
        name=[IdentityInfo(language="eng", value=parsed["name"])],
    )
    
    # Note: Ensure paths inside your config.toml now also reflect 
    # the .mosip_keys/ prefix if they are relative to the root!
    response = authenticator.auth(
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

    return MOSIPVerificationResult(
        verified=auth_status,
        individual_id=parsed["individual_id"],
        first_name=parsed["first_name"],
        last_name=parsed["last_name"],
        transaction_id=transaction_id,
        message="Identity verified." if auth_status else "Verification failed.",
    )

async def verify_qr(qr_data: str) -> MOSIPVerificationResult:
    parsed = parse_philsys_qr(qr_data)
    if parsed is None:
        return MOSIPVerificationResult(
            verified=False,
            message="Invalid QR code format.",
        )
    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: _do_mosip_auth(parsed))
    except Exception as e:
        return MOSIPVerificationResult(
            verified=False,
            message=f"MOSIP error: {str(e)}",
        )