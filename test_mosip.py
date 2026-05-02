import asyncio
from mosip import verify_qr

async def run_test():
    # This simulates the exact string your ESP8266 would send after scanning QR-1
    # Use the exact strings that worked in yes_no_auth.py
    mock_qr_data = '{"uin": "5408602380", "name": "Yuki Nakashima", "dob": "1997/09/12"}'
    
    print("--- Starting MOSIP Verification Test ---")
    print(f"Testing with UIN: 5408602380")
    
    result = await verify_qr(mock_qr_data)

    # --- DEBUG PRINTING START ---
    print("\n--- DEBUG INFO ---")
    print(f"Raw Result Object: {result}")
    # This specifically looks for error details if the result failed
    if not result.verified:
        print(f"Internal Message: {result.message}")
    print("------------------\n")
    # --- DEBUG PRINTING END ---
    
    if result.verified:
        print("✅ SUCCESS: MOSIP confirmed this identity!")
        print(f"Resident: {result.first_name} {result.last_name}")
        print(f"Transaction ID: {result.transaction_id}")
    else:
        print("❌ FAILED: Verification unsuccessful.")
        print(f"Reason: {result.message}")

if __name__ == "__main__":
    asyncio.run(run_test())