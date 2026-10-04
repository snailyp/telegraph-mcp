"""Entry points: serve over Streamable HTTP, or run the account bootstrap."""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Sequence

from .config import DEFAULT_MCP_PATH, Settings, get_settings
from .server import build_server_if_ready


def _serve(settings: Settings) -> None:
    server = build_server_if_ready(settings)
    server.run(
        transport="http",
        host=settings.host,
        port=settings.port,
        path=settings.mcp_path,
        stateless_http=True,
    )


async def _bootstrap(short_name: str, author_name: str | None) -> int:
    """Create a Telegraph account once and print its token.

    Deliberately not part of startup: minting accounts silently would leave an
    operator with accounts they never asked for, and a token lost this way makes
    every page published under it permanently uneditable. See ADR 1.
    """

    from .telegraph import create_account

    account = await create_account(short_name, author_name=author_name)
    print("Telegraph account created.")
    print(f"  short_name:   {account.short_name}")
    if account.author_name:
        print(f"  author_name:  {account.author_name}")
    print()
    print("Add this to your configuration — it is the only time it is shown:")
    print()
    print(f"TELEGRAPH_ACCESS_TOKEN={account.access_token}")
    print()
    if account.auth_url:
        print("To log into telegra.ph as this account, open:")
        print(f"  {account.auth_url}")
        print("(This login link is single-use and expires in 5 minutes.)")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="telegraph-mcp",
        description="Publish Markdown documents as Telegraph pages over MCP.",
    )
    subparsers = parser.add_subparsers(dest="command")

    serve = subparsers.add_parser("serve", help="Run the MCP server (default).")
    serve.add_argument("--host", default=None, help="Bind address.")
    serve.add_argument("--port", type=int, default=None, help="Bind port.")
    serve.add_argument("--path", default=None, help="MCP endpoint path.")

    bootstrap = subparsers.add_parser(
        "bootstrap",
        help="Create a Telegraph account and print its access token.",
    )
    bootstrap.add_argument(
        "short_name",
        nargs="?",
        default="telegraph-mcp",
        help="Account label, 1-32 characters.",
    )
    bootstrap.add_argument(
        "--author-name",
        default=None,
        help="Default author byline for pages published under this account.",
    )

    args = parser.parse_args(argv)

    if args.command == "bootstrap":
        return asyncio.run(_bootstrap(args.short_name, args.author_name))

    settings = get_settings()
    if args.command == "serve":
        overrides = {
            "host": args.host,
            "port": args.port,
            "mcp_path": args.path,
        }
        settings = settings.model_copy(
            update={key: value for key, value in overrides.items() if value is not None}
        )
    _serve(settings)
    return 0


if __name__ == "__main__":
    sys.exit(main())