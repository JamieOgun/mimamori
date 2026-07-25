"""Read-only preflight check for Twilio config. Places NO calls, costs nothing.

Run:  uv run python scripts/check_twilio.py [+81DESTINATION]

Pass a destination number to also check whether that country's dialing is
enabled and whether the number is reachable given your account type.
"""

from __future__ import annotations

import sys

from twilio.rest import Client

from mimamori import config


def _iso_country(number: str) -> str:
    """Best-effort ISO country code from an E.164 prefix (just what we need)."""
    prefixes = {"+81": "JP", "+44": "GB", "+1": "US"}
    for prefix, iso in prefixes.items():
        if number.startswith(prefix):
            return iso
    return ""


def main() -> None:
    dest = sys.argv[1] if len(sys.argv) > 1 else None

    print("Building Twilio client from .env ...")
    client = Client(*config.twilio_client_args())

    account = client.api.v2010.accounts(config.TWILIO_ACCOUNT_SID).fetch()
    # account.type is "Trial" or "Full".
    print(f"  auth OK — status: {account.status}, type: {account.type}")
    is_trial = account.type == "Trial"

    from_number = config.PHONE_NUMBER_FROM
    print(f"\nOrigin number in .env: {from_number}")

    owned = [n.phone_number for n in client.incoming_phone_numbers.list(limit=50)]
    verified = [c.phone_number for c in client.outgoing_caller_ids.list(limit=50)]

    print("\nTwilio numbers you OWN (usable as origin/from):")
    print("  " + (", ".join(owned) if owned else "(none)"))
    print("\nVerified caller IDs (usable as destination on trial):")
    print("  " + (", ".join(verified) if verified else "(none)"))

    if from_number in owned:
        print(f"\n✅ {from_number} is a Twilio number you own — good as FROM.")
    elif from_number in verified:
        print(f"\n⚠️  {from_number} is only a verified caller ID, not owned.")
    else:
        print(f"\n❌ {from_number} is neither owned nor verified. Fix PHONE_NUMBER_FROM.")

    if not dest:
        print("\n(Tip: pass a destination, e.g. `... check_twilio.py +8190...`, to "
              "check Japan dialing + reachability.)")
        return

    iso = _iso_country(dest)
    print(f"\n--- Destination check: {dest} ({iso or 'unknown country'}) ---")

    # 1. Geographic (dialing) permissions for the destination country.
    if iso:
        try:
            country = client.voice.v1.dialing_permissions.countries(iso).fetch()
            print(f"  Dialing to {iso}: low_risk_enabled="
                  f"{country.low_risk_numbers_enabled}, "
                  f"high_risk_special_enabled="
                  f"{country.high_risk_special_numbers_enabled}")
            if not country.low_risk_numbers_enabled:
                print(f"  ❌ Calls to {iso} are BLOCKED. Enable it: Console → Voice → "
                      "Settings → Geographic Permissions.")
            else:
                print(f"  ✅ Calls to {iso} are enabled.")
        except Exception as exc:  # noqa: BLE001
            print(f"  (could not read dialing permissions: {exc})")

    # 2. Trial accounts can only call verified numbers.
    if is_trial:
        if dest in verified:
            print(f"  ✅ {dest} is verified — reachable on your trial account.")
        else:
            print(f"  ❌ Trial account: {dest} must be a VERIFIED caller ID first. "
                  "Console → Phone Numbers → Verified Caller IDs → add it "
                  "(you need to answer that phone to enter the code).")
    else:
        print("  ✅ Full account — no per-number verification required "
              "(ensure you have consent to call).")


if __name__ == "__main__":
    main()
