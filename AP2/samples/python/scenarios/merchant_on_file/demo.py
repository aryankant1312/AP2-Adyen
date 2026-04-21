"""Demo: Merchant-on-File (Mode 2) from the Shopper's perspective.

Runs without A2A transport so you can see the data boundary clearly.
Invoke from the AP2 repo root:

    python samples/python/scenarios/merchant_on_file/demo.py

What this demonstrates:
  1. The user has a signed CartMandate and clicks checkout.
  2. The Shopping Agent asks the *merchant* (not the CP) for saved methods.
  3. The merchant returns aliases + last4 only. No PAN / CVV / raw VPA.
  4. User picks an alias. The Shopping Agent asks the merchant for a
     short-lived charge token.
  5. That token -- and ONLY that token -- is embedded in the PaymentMandate.
  6. Later the merchant/MPP presents the token to the PSP, which charges
     the underlying credential internally and returns a receipt. At no
     point does the shopper's code see raw credentials.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Make the sample sources importable without installing the package.
# layout: samples/python/scenarios/merchant_on_file/demo.py -> samples/python/src
PY_SAMPLES_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PY_SAMPLES_ROOT / "src"))

from roles.merchant_agent import customer_vault  # noqa: E402
from roles.merchant_agent import psp_vault  # noqa: E402


DIVIDER = "-" * 68


def banner(title: str) -> None:
  print(f"\n{DIVIDER}\n{title}\n{DIVIDER}")


def show(label: str, obj) -> None:
  print(f"{label}:")
  print(json.dumps(obj, indent=2, default=str))


def main() -> None:
  user_email = "aarav.sharma@example.com"
  payment_mandate_id = "pm_mandate_demo_0001"
  amount = "429.00"
  currency = "INR"

  banner("SCENARIO")
  print(
      "Returning pharmacy customer clicks CHECKOUT on a finalized CartMandate."
  )
  print(f"  user:   {user_email}")
  print(f"  total:  {currency} {amount}")

  # ------------------------------------------------------------------
  # Step 1 — Shopping Agent asks merchant for saved payment methods.
  # Under the hood this goes over A2A to merchant_agent.get_merchant_on_
  # file_payment_methods(). Here we call the same service layer directly.
  # ------------------------------------------------------------------
  banner("1. Shopper -> Merchant: get_merchant_on_file_payment_methods")
  on_file = customer_vault.get_on_file_methods(user_email)
  show("Agent-visible response", on_file)
  print(
      "\nNote: the expired 'Old Visa' is filtered out upstream by the PSP's"
      " is_still_valid() check. The agent never learns it exists."
  )

  # ------------------------------------------------------------------
  # Step 2 — Shopping Agent shows a picker and user chooses an alias.
  # ------------------------------------------------------------------
  banner("2. Shopping Agent UI picker")
  for i, m in enumerate(on_file, start=1):
    print(f"  [{i}] {m['alias']}   ({m['nickname']})")
  chosen = on_file[0]["alias"]
  print(f"\nUser selects -> {chosen}")

  # ------------------------------------------------------------------
  # Step 3 — Shopper asks merchant to mint a charge token for that alias.
  # alias -> psp_ref resolution is MERCHANT-INTERNAL. The agent never
  # sees the psp_ref (pm_XXXX) or the PAN.
  # ------------------------------------------------------------------
  banner("3. Shopper -> Merchant: create_merchant_on_file_token")
  psp_ref = customer_vault.resolve_alias_to_psp_ref(user_email, chosen)
  assert psp_ref is not None
  charge_token = psp_vault.mint_charge_token(psp_ref, user_email)
  print(f"  (merchant internal) alias '{chosen}' -> psp_ref '{psp_ref}'")
  print(f"  returned to shopper: {{'alias': '{chosen}', 'token': '{charge_token}'}}")
  print("  ^ The shopper only receives the charge token + alias.")

  # ------------------------------------------------------------------
  # Step 4 — Shopper builds the PaymentMandate with the token (not
  # the PSP ref, not the PAN). Shown as a trimmed dict for brevity.
  # ------------------------------------------------------------------
  banner("4. Shopper builds PaymentMandate (credential token only)")
  payment_mandate_contents = {
      "payment_mandate_id": payment_mandate_id,
      "payment_response": {
          "method_name": "CARD",
          "details": {
              "token": {
                  "value": charge_token,
                  "url": "https://merchant.example/a2a",
                  "source": "merchant_on_file",
              }
          },
          "payer_email": user_email,
      },
      "payment_details_total": {
          "amount": {"currency": currency, "value": amount},
      },
  }
  show("PaymentMandate.contents (trimmed)", payment_mandate_contents)

  # The user then signs the mandate on-device (ECDSA P-256). For the demo
  # we just bind the token to the mandate id (what the real CP/merchant
  # path does in handle_signed_payment_mandate()).
  psp_vault.bind_mandate(charge_token, payment_mandate_id)
  print("\nCharge token bound to PaymentMandate id (one-shot).")

  # ------------------------------------------------------------------
  # Step 5 — Payment time. The MPP (via the merchant) asks the PSP to
  # charge. The PSP resolves the token -> psp_ref -> raw creds INTERNALLY
  # and only returns a transaction id + auth code.
  # ------------------------------------------------------------------
  banner("5. MPP -> PSP: charge(token, mandate_id)")
  result = psp_vault.charge(
      token=charge_token,
      payment_mandate_id=payment_mandate_id,
      amount=amount,
      currency=currency,
  )
  show("PSP response (safe fields only)", result)

  # ------------------------------------------------------------------
  # Step 6 — Replay protection: the token is one-shot.
  # ------------------------------------------------------------------
  banner("6. Replay attempt (should fail)")
  replay = psp_vault.charge(
      token=charge_token,
      payment_mandate_id=payment_mandate_id,
      amount=amount,
      currency=currency,
  )
  show("Replay result", replay)

  banner("DONE")
  print(
      "At no step did the Shopping Agent layer touch a PAN, CVV, VPA, or"
      " even a psp_ref. Only the alias and the opaque charge token."
  )


if __name__ == "__main__":
  main()
