"""Allow running Charter MCP server as: python3 -m charter.mcp_server"""

import asyncio
from charter.mcp_server import run_stdio

asyncio.run(run_stdio())
