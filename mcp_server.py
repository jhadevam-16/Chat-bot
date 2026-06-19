import asyncio
from mcp.server import Server
from mcp.server.stdio import stdio_server

app = Server("azure-datalake-server")

@app.list_tools()
async def list_tools():
    # ✅ Import only when asked — not at startup
    from tools import get_tool_definitions
    return get_tool_definitions()

@app.call_tool()
async def call_tool(name: str, arguments: dict):
    # ✅ Import only when a tool is called
    from tools import handle_tool_call
    return handle_tool_call(name, arguments)

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )

if __name__ == "__main__":
    asyncio.run(main())