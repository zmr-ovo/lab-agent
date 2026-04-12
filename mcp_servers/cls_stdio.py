"""CLS MCP 的 stdio 入口（不改 cls_server.py 的 HTTP __main__）。

在项目根目录、已激活虚拟环境下使用，例如：
  python -m mcp_servers.cls_stdio
"""

from mcp_servers.cls_server import mcp

if __name__ == "__main__":
    mcp.run(transport="stdio")
