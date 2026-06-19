import sys
import logging
from mcp import types
from azure_loader import list_files, read_file, read_file_chunk, get_file_properties, sample_file, search_in_file
import os
from dotenv import load_dotenv

load_dotenv()
def get_tool_definitions() -> list[types.Tool]:
    return [
        types.Tool(name="list_files", description="List files in a folder.", inputSchema={"type": "object", "properties": {"folder_path": {"type": "string"}}, "required": []}),
        types.Tool(name="get_file_properties", description="Get file size and read recommendation. Call this FIRST before reading.", inputSchema={"type": "object", "properties": {"file_path": {"type": "string"}}, "required": ["file_path"]}),
        types.Tool(name="read_file", description="Read small files only (<50KB).", inputSchema={"type": "object", "properties": {"file_path": {"type": "string"}}, "required": ["file_path"]}),
        types.Tool(name="read_file_chunk", description="Read a section of a file by line numbers.", inputSchema={"type": "object", "properties": {"file_path": {"type": "string"}, "start_line": {"type": "integer"}, "num_lines": {"type": "integer"}}, "required": ["file_path"]}),
        types.Tool(name="sample_file", description="Quickly sample first, middle and last lines of a large file.", inputSchema={"type": "object", "properties": {"file_path": {"type": "string"}}, "required": ["file_path"]}),
        types.Tool(name="search_in_file", description="Search for a value in a specific column of a large file.", inputSchema={"type": "object", "properties": {"file_path": {"type": "string"}, "search_column": {"type": "string"}, "search_value": {"type": "string"}, "max_results": {"type": "integer"}}, "required": ["file_path", "search_column", "search_value"]}),
    ]


def handle_tool_call(name: str, arguments: dict) -> list[types.TextContent]:
    logger.debug(f"Tool called: {name} | Args: {arguments}")

    try:
        # ✅ Import azure_loader only when a tool is actually called
        from azure_loader import list_files, read_file, read_file_chunk, get_file_properties, sample_file, search_in_file

        if name == "list_files":
            result = list_files(arguments.get("folder_path", "/"))
            return [types.TextContent(type="text", text=str(result))]

        elif name == "get_file_properties":
            file_path = arguments.get("file_path")
            if not file_path:
                return [types.TextContent(type="text", text="Error: file_path required")]
            return [types.TextContent(type="text", text=str(get_file_properties(file_path)))]

        elif name == "read_file":
            file_path = arguments.get("file_path")
            if not file_path:
                return [types.TextContent(type="text", text="Error: file_path required")]
            return [types.TextContent(type="text", text=str(read_file(file_path)))]

        elif name == "read_file_chunk":
            file_path = arguments.get("file_path")
            if not file_path:
                return [types.TextContent(type="text", text="Error: file_path required")]
            return [types.TextContent(type="text", text=str(read_file_chunk(file_path, arguments.get("start_line", 0), arguments.get("num_lines", 100))))]

        elif name == "sample_file":
            file_path = arguments.get("file_path")
            if not file_path:
                return [types.TextContent(type="text", text="Error: file_path required")]
            return [types.TextContent(type="text", text=str(sample_file(file_path)))]

        elif name == "search_in_file":
            file_path = arguments.get("file_path")
            search_column = arguments.get("search_column")
            search_value = arguments.get("search_value")
            if not all([file_path, search_column, search_value]):
                return [types.TextContent(type="text", text="Error: file_path, search_column, search_value all required")]
            return [types.TextContent(type="text", text=str(search_in_file(file_path, search_column, search_value, arguments.get("max_results", 10))))]

        else:
            return [types.TextContent(type="text", text=f"Unknown tool: {name}")]

    except Exception as e:
        import traceback
        logger.error(traceback.format_exc())
        return [types.TextContent(type="text", text=f"Error in {name}: {str(e)}")]

logging.basicConfig(
    level=logging.DEBUG,
    stream=sys.stderr,
    format="%(levelname)s: %(message)s"
)
logger = logging.getLogger(__name__)


def get_tool_definitions() -> list[types.Tool]:
    return [

        # ── Tool 1 ──────────────────────────────────────────────────────────
        types.Tool(
            name="list_files",
            description="List all files and folders in a folder in Azure Data Lake.",
            inputSchema={
                "type": "object",
                "properties": {
                    "folder_path": {
                        "type": "string",
                        "description": "Folder path. Use '/' for root or 'sales/2024' for subfolders."
                    }
                },
                "required": []
            }
        ),

        # ── Tool 2 ──────────────────────────────────────────────────────────
        types.Tool(
            name="get_file_properties",
            description="""Get properties of a file such as size, type, and last modified date.
            Also returns a recommendation on HOW to read the file based on its size.
            ALWAYS call this tool FIRST before reading any file.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Full file path e.g. 'MaintenanceSolution.sql'"
                    }
                },
                "required": ["file_path"]
            }
        ),

        # ── Tool 3 ──────────────────────────────────────────────────────────
        types.Tool(
            name="read_file",
            description="""Read the full contents of a file from Azure Data Lake.
            Only use this for SMALL files (under 50KB) as recommended by get_file_properties.
            For larger files always use read_file_chunk instead.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Full file path e.g. 'report.csv'"
                    }
                },
                "required": ["file_path"]
            }
        ),

        # ── Tool 4 ──────────────────────────────────────────────────────────
        types.Tool(
            name="read_file_chunk",
            description="""Read a specific section of a file by line numbers.
            Use this for MEDIUM, LARGE, or VERY LARGE files as recommended by get_file_properties.
            Always check get_file_properties first to know which line range to read.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Full file path e.g. 'MaintenanceSolution.sql'"
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "Line number to start reading from. Default is 0 (beginning)."
                    },
                    "num_lines": {
                        "type": "integer",
                        "description": "Number of lines to read. Default is 100. Use 20-50 for very large files."
                    }
                },
                "required": ["file_path"]
            }
        ),

        # ── Tool 5 ──────────────────────────────────────────────────────────
        types.Tool(
            name="sample_file",
            description="""Quickly sample a large file by reading only the
            first 10 lines, middle 5 lines, and last 5 lines.
            Use this for LARGE or VERY LARGE files to get a quick overview
            without downloading the whole file. Much faster than read_file.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Full file path e.g. 'MaintenanceSolution.sql'"
                    }
                },
                "required": ["file_path"]
            }
        ),

        # ── Tool 6 ──────────────────────────────────────────────────────────
        types.Tool(
            name="search_in_file",
            description="""Search for a specific value in a specific column of a large file.
            Streams through the file chunk by chunk without loading it fully into memory.
            Perfect for finding a specific person, ID, or record in millions of rows.
            Use this instead of read_file for any search/lookup task.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Full file path e.g. 'customers.csv'"
                    },
                    "search_column": {
                        "type": "string",
                        "description": "Column name to search in e.g. 'name', 'email', 'customer_id'"
                    },
                    "search_value": {
                        "type": "string",
                        "description": "Value to search for e.g. 'John Smith', 'john@email.com', '12345'"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of matching rows to return. Default is 10."
                    }
                },
                "required": ["file_path", "search_column", "search_value"]
            }
        ),

    ]  # ← end of get_tool_definitions()


def handle_tool_call(name: str, arguments: dict) -> list[types.TextContent]:
    logger.debug(f"Tool called: {name} | Args: {arguments}")

    try:
        # ── Tool 1 Handler ───────────────────────────────────────────────────
        if name == "list_files":
            folder_path = arguments.get("folder_path", "/")
            result = list_files(folder_path)
            return [types.TextContent(type="text", text=str(result))]

        # ── Tool 2 Handler ───────────────────────────────────────────────────
        elif name == "get_file_properties":
            file_path = arguments.get("file_path")
            if not file_path:
                return [types.TextContent(type="text", text="Error: file_path is required")]
            result = get_file_properties(file_path)
            return [types.TextContent(type="text", text=str(result))]

        # ── Tool 3 Handler ───────────────────────────────────────────────────
        elif name == "read_file":
            file_path = arguments.get("file_path")
            if not file_path:
                return [types.TextContent(type="text", text="Error: file_path is required")]
            result = read_file(file_path)
            return [types.TextContent(type="text", text=str(result))]

        # ── Tool 4 Handler ───────────────────────────────────────────────────
        elif name == "read_file_chunk":
            file_path = arguments.get("file_path")
            if not file_path:
                return [types.TextContent(type="text", text="Error: file_path is required")]
            start_line = arguments.get("start_line", 0)
            num_lines = arguments.get("num_lines", 100)
            result = read_file_chunk(file_path, start_line, num_lines)
            return [types.TextContent(type="text", text=str(result))]

        # ── Tool 5 Handler ───────────────────────────────────────────────────
        elif name == "sample_file":
            file_path = arguments.get("file_path")
            if not file_path:
                return [types.TextContent(type="text", text="Error: file_path is required")]
            result = sample_file(file_path)
            return [types.TextContent(type="text", text=str(result))]

        # ── Tool 6 Handler ───────────────────────────────────────────────────
        elif name == "search_in_file":
            file_path = arguments.get("file_path")
            search_column = arguments.get("search_column")
            search_value = arguments.get("search_value")
            max_results = arguments.get("max_results", 10)
            if not all([file_path, search_column, search_value]):
                return [types.TextContent(type="text", text="Error: file_path, search_column and search_value are all required")]
            result = search_in_file(file_path, search_column, search_value, max_results)
            return [types.TextContent(type="text", text=str(result))]

        # ── Unknown Tool ─────────────────────────────────────────────────────
        else:
            logger.warning(f"Unknown tool called: {name}")
            return [types.TextContent(type="text", text=f"Error: Unknown tool '{name}'")]

    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        logger.error(f"Tool error in '{name}': {error_detail}")
        return [types.TextContent(type="text", text=f"Error in {name}: {str(e)}")]