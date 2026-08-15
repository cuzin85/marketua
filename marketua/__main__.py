"""Entry point: ``python -m marketua`` or the ``marketua`` console script.

Runs the MCP server over stdio — an MCP client spawns it as a child process.
"""

from marketua.server import mcp


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
