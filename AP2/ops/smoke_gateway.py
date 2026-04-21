"""End-to-end smoke test: connect to the gateway over streamable-HTTP MCP
and walk the happy path: search → cart → finalize → MOF → token →
build_payment_mandate → sign → submit → complete_challenge.

Run with the four services already up:

    python ops/smoke_gateway.py                      # localhost:8080
    python ops/smoke_gateway.py --base-url \
        https://abc-123.trycloudflare.com/mcp        # remote tunnel
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


GATEWAY = os.environ.get("GATEWAY_URL", "http://127.0.0.1:8080/mcp")
TOKEN   = os.environ.get("MCP_TOKEN", "dev-token-please-change")


def _data(result) -> Any:
    """Pull the structured payload off an MCP CallToolResult.

    FastMCP shapes vary by return type:
      * dict-return  → structuredContent is the dict (sometimes under
        "result"); content[0].text is the JSON-encoded same.
      * list-return  → structuredContent = {"result": [...]} OR raw list;
        content[0].text is JSON list.
    Strategy: try content[0].text first (always JSON), fall back to
    structuredContent.
    """
    def _unwrap(v):
        if isinstance(v, dict) and set(v.keys()) == {"result"}:
            return v["result"]
        return v

    # 1. structuredContent has the full payload (a single object even for
    #    list-returning tools, wrapped under "result").
    sc = (getattr(result, "structuredContent", None)
          or getattr(result, "structured_content", None))
    if sc is not None:
        return _unwrap(sc)

    # 2. Fall back to gathering every content text part as JSON.
    items = []
    for c in getattr(result, "content", None) or []:
        text = getattr(c, "text", None)
        if not text:
            continue
        try:
            items.append(json.loads(text))
        except Exception:
            items.append(text)
    if len(items) == 1:
        return items[0]
    return items


async def main(gateway: str = GATEWAY, token: str = TOKEN) -> int:
    print(f"connecting to {gateway}")
    async with streamablehttp_client(
        url=gateway,
        headers={"Authorization": f"Bearer {token}"},
    ) as (read, write, _close):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            tool_names = sorted(t.name for t in tools.tools)
            print(f"tools: {len(tool_names)} — {tool_names[:6]}…")

            # Pick the first seeded customer that actually has an MOF method,
            # so the smoke is robust to whichever names the synth generator
            # rolled this run.
            email = "aarav.sharma@example.com"
            try:
                import sqlite3, pathlib
                db = (pathlib.Path(__file__).resolve().parent.parent
                      / "data" / "pharmacy.sqlite")
                if db.exists():
                    c = sqlite3.connect(str(db))
                    row = c.execute(
                        "SELECT email FROM merchant_on_file_methods "
                        "GROUP BY email ORDER BY count(*) DESC LIMIT 1"
                    ).fetchone()
                    c.close()
                    if row:
                        email = row[0]
            except Exception as exc:
                print(f"(could not auto-pick customer: {exc})")
            print(f"using customer email = {email!r}")

            print("\n[1] search_products('medicine for fever')")
            r = await session.call_tool("search_products",
                                          {"query": "medicine for fever",
                                           "store_location": "London",
                                           "limit": 5})
            payload = _data(r) or {}
            # Widget-wrapped envelope: {products: [...], store, query}
            products = (payload.get("products")
                        if isinstance(payload, dict) else payload) or []
            print(json.dumps(products[:2], indent=2))
            if not products:
                print("FAIL no products"); return 2
            chosen = products[0]

            print("\n[2] start_cart")
            r = await session.call_tool("start_cart",
                                          {"user_email": email,
                                           "store_location": "London"})
            cart = _data(r)
            cart_id = cart["cart_id"]
            sess_id = cart.get("session_id")
            print(f"cart_id={cart_id} session_id={sess_id}")

            print(f"\n[3] add_cart_item {chosen['product_ref']} x2")
            r = await session.call_tool("add_cart_item",
                                          {"cart_id": cart_id,
                                           "product_ref": chosen["product_ref"],
                                           "qty": 2})
            view = _data(r)
            print(f"subtotal=£{view.get('subtotal_gbp')} total=£{view.get('total_gbp')}")

            print("\n[4] get_merchant_on_file_payment_methods")
            r = await session.call_tool(
                "get_merchant_on_file_payment_methods",
                {"user_email": email})
            payload = _data(r) or {}
            mof = (payload.get("methods")
                   if isinstance(payload, dict) else payload) or []
            print(f"got {len(mof)} MOF methods")
            for m in mof[:3]:
                print(f"  alias={m.get('alias')} brand={m.get('brand')} last4={m.get('last4')}")

            if not mof:
                print("(no MOF methods — is the customer in the seed DB?)")
                return 3

            print("\n[5] finalize_cart")
            r = await session.call_tool("finalize_cart",
                                          {"cart_id": cart_id,
                                           "mcp_session_id": sess_id})
            fin = _data(r)
            if fin and fin.get("merchant_authorization"):
                print(f"finalized: total=£{fin.get('total_gbp')} JWT len={len(fin['merchant_authorization'])}")
            else:
                print("finalize result:", json.dumps(fin, indent=2)[:600])

            alias = mof[0]["alias"]
            print(f"\n[6] create_merchant_on_file_token alias={alias!r}")
            r = await session.call_tool("create_merchant_on_file_token",
                                          {"user_email": email,
                                           "alias": alias,
                                           "cart_id": cart_id,
                                           "mcp_session_id": sess_id})
            tok = _data(r)
            print("token:", json.dumps(tok, indent=2)[:400])

            if not tok or not tok.get("token"):
                print("(no token — stopping; this is expected if MA returned an error above)")
                return 0

            print("\n[7] build_payment_mandate")
            r = await session.call_tool("build_payment_mandate",
                                          {"cart_id": cart_id,
                                           "token": tok["token"],
                                           "source": "merchant_on_file",
                                           "user_email": email,
                                           "payer_name": email.split("@")[0]
                                                          .replace(".", " ")
                                                          .title(),
                                           "mcp_session_id": sess_id})
            built = _data(r)
            print(f"mandate_id={built.get('payment_mandate_id')}")

            print("\n[8] sign_payment_mandate")
            r = await session.call_tool("sign_payment_mandate",
                                          {"mandate_id": built["payment_mandate_id"],
                                           "mcp_session_id": sess_id})
            print("signed:", _data(r))

            print("\n[9] submit_payment")
            r = await session.call_tool("submit_payment",
                                          {"mandate_id": built["payment_mandate_id"],
                                           "mcp_session_id": sess_id,
                                           "user_email": email})
            sub = _data(r)
            print("submit result:", json.dumps(sub, indent=2)[:600])

            if sub.get("status") == "ChallengeShopper":
                cid = sub.get("challenge_id")
                print(f"\n[10] complete_challenge(otp=123) cid={cid}")
                r = await session.call_tool("complete_challenge",
                                              {"challenge_id": cid,
                                               "challenge_response": "123",
                                               "mcp_session_id": sess_id})
                print("complete:", json.dumps(_data(r), indent=2)[:600])
    print("\nDONE")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base-url",
                   help="Full MCP URL incl. /mcp suffix "
                        "(default: $GATEWAY_URL or http://127.0.0.1:8080/mcp)")
    p.add_argument("--token",
                   help="Bearer token (default: $MCP_TOKEN or built-in dev value)")
    args = p.parse_args()
    sys.exit(asyncio.run(main(args.base_url or GATEWAY,
                              args.token or TOKEN)))
