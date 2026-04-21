"""Generate fresh MCP bearer tokens.

Usage:
    python ops/gen_token.py            # print 2 fresh tokens to stdout
    python ops/gen_token.py --write-env  # also rotate MCP_TOKENS in ops/envs/.env

The HTTP gateway accepts any token in ``MCP_TOKENS`` (comma-separated).
We default to *two* tokens so a demo presenter can connect Claude and
ChatGPT side-by-side without sharing the same secret.
"""

from __future__ import annotations

import argparse
import os
import secrets
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_ENV = _REPO_ROOT / "ops" / "envs" / ".env"
_DEFAULT_EXAMPLE = _REPO_ROOT / "ops" / "envs" / ".env.example"


def gen(n: int = 2, nbytes: int = 32) -> list[str]:
    return [secrets.token_urlsafe(nbytes) for _ in range(n)]


def _seed_env_from_example_if_missing(env_path: Path) -> None:
    if env_path.exists():
        return
    if not _DEFAULT_EXAMPLE.exists():
        env_path.write_text("", encoding="utf-8")
        return
    env_path.write_text(_DEFAULT_EXAMPLE.read_text(encoding="utf-8"),
                        encoding="utf-8")


def write_env(tokens: list[str], env_path: Path = _DEFAULT_ENV) -> None:
    env_path.parent.mkdir(parents=True, exist_ok=True)
    _seed_env_from_example_if_missing(env_path)
    body = env_path.read_text(encoding="utf-8")
    line = "MCP_TOKENS=" + ",".join(tokens)
    if "MCP_TOKENS=" in body:
        new_lines = []
        for ln in body.splitlines():
            new_lines.append(line if ln.startswith("MCP_TOKENS=") else ln)
        body = "\n".join(new_lines)
        if not body.endswith("\n"):
            body += "\n"
    else:
        body = (body.rstrip() + "\n" + line + "\n") if body.strip() else line + "\n"
    env_path.write_text(body, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("-n", "--count", type=int, default=2,
                   help="number of tokens to generate (default 2)")
    p.add_argument("--write-env", action="store_true",
                   help="rotate MCP_TOKENS= in ops/envs/.env")
    p.add_argument("--env-path", default=str(_DEFAULT_ENV),
                   help="path to .env (default: ops/envs/.env)")
    args = p.parse_args(argv)

    tokens = gen(args.count)
    print("# fresh MCP bearer tokens (copy into your connector UI):")
    for t in tokens:
        print(t)

    if args.write_env:
        write_env(tokens, Path(args.env_path))
        print(f"\nupdated {args.env_path}: MCP_TOKENS rotated to {len(tokens)} value(s).")
    else:
        print("\n(re-run with --write-env to rotate ops/envs/.env)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
