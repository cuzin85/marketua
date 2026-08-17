"""marketua — MCP server for searching Ukrainian marketplaces."""

from importlib.metadata import PackageNotFoundError, version as _package_version

try:
    __version__ = _package_version("marketua")
except PackageNotFoundError:  # running from a source checkout without install
    __version__ = "0.0.0"
