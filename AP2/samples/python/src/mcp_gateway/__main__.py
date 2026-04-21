"""CLI entry point — ``python -m mcp_gateway`` (stdio) or ``--http``."""

from __future__ import annotations

import argparse
import logging
import sys

from .server import build_http_app, build_mcp


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="AP2 pharmacy MCP gateway — stdio (default) or HTTP.",
    )
    p.add_argument("--http", default=None,
                   help="bind address for streamable-HTTP transport, "
                        "e.g. 0.0.0.0:8080 (otherwise stdio)")
    p.add_argument("--name", default="ap2-pharmacy",
                   help="MCP server name advertised to clients")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    mcp = build_mcp(args.name)

    if args.http:
        host, _, port_str = args.http.partition(":")
        host = host or "0.0.0.0"
        port = int(port_str or "8080")
        # Build the gated Starlette wrapper around FastMCP's
        # streamable-HTTP app and serve via uvicorn so we can attach
        # bearer-auth middleware + public health/OAuth routes.
        app = build_http_app(mcp)
        try:
            import uvicorn
        except ImportError as exc:  # pragma: no cover
            raise SystemExit(
                "uvicorn is required for --http mode "
                "(`pip install uvicorn[standard]`)"
            ) from exc
        uvicorn.run(app, host=host, port=port,
                    log_level="debug" if args.verbose else "info")
    else:
        mcp.run()  # stdio default
    return 0


if __name__ == "__main__":
    sys.exit(main())
