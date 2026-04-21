"""Order-history tools — pure SQLite reads."""

from __future__ import annotations

from pharmacy_data import queries

from ..schemas import PastOrderDetail, PastOrderHead


def register(mcp) -> None:

    @mcp.tool()
    async def list_past_orders(user_email: str,
                                limit: int = 20) -> list[dict]:
        """Return order headers for a customer, newest first."""
        rows = queries.list_past_orders(email=user_email, limit=limit)
        return [PastOrderHead(**{k: r.get(k) for k in
                                 PastOrderHead.model_fields}).model_dump()
                for r in rows]

    @mcp.tool()
    async def get_order(order_id: str) -> dict | None:
        """Full order with line items (joins ``products`` for titles)."""
        row = queries.get_order(order_id)
        if not row:
            return None
        return PastOrderDetail(
            order_id=row["order_id"],
            placed_at=row["placed_at"],
            total_gbp=row["total_gbp"],
            store_location=row.get("store_location"),
            stored_method_id=row.get("stored_method_id"),
            lines=row.get("lines", []),
        ).model_dump()
