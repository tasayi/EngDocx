"""CLI entrypoint for running EngDoc MCP Server directly via python -m engdoc.mcp."""

from __future__ import annotations

import argparse

from engdoc.mcp.server import create_mcp_server


def main() -> None:
    parser = argparse.ArgumentParser(description="EngDoc Model Context Protocol (MCP) Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
        help="Transport protocol to use (default: stdio)",
    )
    parser.add_argument(
        "--host", default="127.0.0.1", help="Host to bind for HTTP/SSE (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--port", type=int, default=8000, help="Port to bind for HTTP/SSE (default: 8000)"
    )
    args = parser.parse_args()

    server = create_mcp_server()
    if args.transport == "stdio":
        server.run(transport="stdio")
    elif args.transport == "sse":
        server.run(transport="sse", host=args.host, port=args.port)
    elif args.transport == "streamable-http":
        server.run(transport="streamable-http", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
