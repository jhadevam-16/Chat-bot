import logging
logging.basicConfig(level=logging.WARNING)
logging.getLogger("azure").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

import json
import os
import threading
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

MODEL  = "gpt-4.1-mini"
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

from azure_loader import (
    list_files,
    get_file_properties,
    duckdb_query,
    get_schema_tool,
    read_file,
    list_schema_cache,
    search_file,
    search_column,          # ← NEW
    build_file_index,
    refresh_file_index,
    CONTAINER,
)

context = {
    "current_folder": "/",
    "last_file":      None,
}



SYSTEM_PROMPT = f"""You are an Azure Data Lake assistant for Vaibhav Global Limited.
You help users explore and analyze files stored in Azure Data Lake using plain English.
The Azure container name is: {CONTAINER}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FILE SEARCH RULE (MOST IMPORTANT)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
If user mentions a file name WITHOUT giving the full path:
  → ALWAYS call search_file FIRST to find the full path.
  → Then use the returned full path in duckdb_query or get_schema.
  → NEVER assume or guess a file path.
  → Even partial names work: "salesorder" finds "Sales_SalesOrderLine.parquet"
  → Spaces, underscores, hyphens are all treated the same during search.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
COLUMN SEARCH RULE (NEW)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
If user asks about a column WITHOUT specifying which file it is in:
  → ALWAYS call search_column to find which file(s) contain that column.
  → Then use the returned file path in duckdb_query.
  → NEVER guess which file has the column.

Examples that trigger search_column:
  - "where is CustomerID stored?"
  - "which file has TotalGrossAmount?"
  - "find the column called OrderDate"
  - "I want gross value data" (column location unknown)
  - "show me all discount values" (file unknown)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NAVIGATION RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. When user asks to list files → call list_files
2. Never go recursive — show only what is directly inside the asked folder
3. Only enter a subfolder when user explicitly asks

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SCHEMA RULE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Before writing ANY query on a file you haven't seen yet:
  → Call get_schema first to get column names.
  → Then write precise SQL using actual column names.
  → NEVER guess column names.
If schema is already in conversation history → skip get_schema.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FILE READING RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- .parquet, .csv, .xlsx (ANY size) → ALWAYS use duckdb_query
- Small plain text / JSON (<50KB)  → use read_file
- Never use read_file for parquet or csv

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DUCKDB RULES — you write SQL silently
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- You write SQL. The user NEVER sees or types SQL.
- Reference files as: 'az://folder/subfolder/file.parquet'
- Always LIMIT unless user asks for all rows (default 50)
- For large files filter by date or ID in WHERE clause first.

DUCKDB DATE SYNTAX — always use these, never SQLite syntax:
- Last 6 months  → WHERE col >= CURRENT_DATE - INTERVAL 6 MONTHS
- Last 30 days   → WHERE col >= CURRENT_DATE - INTERVAL 30 DAYS
- Last 1 year    → WHERE col >= CURRENT_DATE - INTERVAL 1 YEAR
- This year      → WHERE YEAR(col) = YEAR(CURRENT_DATE)
- By month       → DATE_TRUNC('month', col)
- Month name     → STRFTIME(col, '%Y-%m')
- NEVER use      → date('now', '-X months')  ← SQLite, NOT DuckDB

WHAT USER SAYS → SQL YOU WRITE:
- "summarize / overview"     → SELECT col1,col2,col3 FROM '...' LIMIT 5
- "how many rows?"           → SELECT COUNT(*) FROM '...'
- "show columns"             → call get_schema instead
- "filter / show where X"    → SELECT ... WHERE col ILIKE '%value%' LIMIT 50
- "group by / count"         → SELECT col, COUNT(*) as total FROM '...' GROUP BY col ORDER BY total DESC LIMIT 30
- "top N by column"          → SELECT ... ORDER BY col DESC LIMIT N
- "last 6 months trend"      → SELECT DATE_TRUNC('month', date_col) as month, SUM(val) FROM '...' WHERE date_col >= CURRENT_DATE - INTERVAL 6 MONTHS GROUP BY 1 ORDER BY 1
- "average / sum / min / max"→ SELECT AVG(col), SUM(col), MIN(col), MAX(col) FROM '...'
- "unique values"            → SELECT DISTINCT col FROM '...' LIMIT 50
- "missing / null values"    → SELECT COUNT(*) - COUNT(col) as missing FROM '...'

NEVER expose SQL in your response. Show results naturally.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
JOIN RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NEVER SELECT * on a JOIN. Always:
  STEP 1 → get_schema on BOTH files
  STEP 2 → find common column
  STEP 3 → SELECT specific columns with LIMIT 50

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EXPORT RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
When user says "save", "export", "download", "Excel" → set export_excel=true.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SUGGESTED ACTIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
After every answer add 2-3 short suggestions on ONE line separated by |."""



TOOLS = [
    # ── Tool 1 — List Files ──────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files and folders directly inside a folder. Not recursive.",
            "parameters": {
                "type": "object",
                "properties": {
                    "directory_path": {
                        "type": "string",
                        "description": "Folder path. Use '/' for root."
                    }
                },
                "required": []
            }
        }
    },

    # ── Tool 2 — File Properties ─────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "get_file_properties",
            "description": "Get file metadata: size, type, last modified. Does not download.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"}
                },
                "required": ["file_path"]
            }
        }
    },

    # ── Tool 3 — Get Schema ──────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "get_schema",
            "description": (
                "Fetch column names of a parquet or csv file. "
                "ALWAYS call this before writing any query on a new file. "
                "Has automatic SDK fallback if DuckDB fails. Results cached."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Full path e.g. 'results/UH_Data.parquet'"
                    }
                },
                "required": ["file_path"]
            }
        }
    },

    # ── Tool 4 — DuckDB Query ────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "duckdb_query",
            "description": (
                "Run SQL on parquet/csv/xlsx files in Azure. "
                "Has automatic SDK fallback if DuckDB unavailable. "
                "Use for ALL data files regardless of size. "
                "Reference files as: 'az://folder/subfolder/file.parquet'. "
                "Set export_excel=true when user asks to save/export/download."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": "SQL using 'az://path/file.parquet' as table name."
                    },
                    "export_excel": {
                        "type": "boolean",
                        "description": "True to save results as Excel on Desktop."
                    }
                },
                "required": ["sql"]
            }
        }
    },

    # ── Tool 5 — Read File ───────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a small plain text or JSON file under 50KB only. Never for parquet/csv.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"}
                },
                "required": ["file_path"]
            }
        }
    },

    # ── Tool 6 — Search File ─────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "search_file",
            "description": (
                "Search entire Data Lake by file name — instant using cached index. "
                "ALWAYS use when user types a file name without full path. "
                "Spaces, underscores and hyphens are treated as the same separator. "
                "Partial names work: 'salesorder' finds 'Sales_SalesOrderLine.parquet'. "
                "Case-insensitive."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_name": {
                        "type": "string",
                        "description": "File name or partial name to search for."
                    }
                },
                "required": ["file_name"]
            }
        }
    },

    # ── Tool 7 — Search Column (NEW) ─────────────────────────
    {
        "type": "function",
        "function": {
            "name": "search_column",
            "description": (
                "Search for a column name across ALL files in the entire Data Lake. "
                "Use this when user asks about a column but doesn't know which file it's in. "
                "Also use when user asks 'which file has column X' or 'where is column Y'. "
                "Checks cached schemas first (instant), then scans remaining files. "
                "Partial names work: 'gross' finds 'TotalGrossAmount'. "
                "ALWAYS call this when file is unknown and user mentions a column name."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "column_name": {
                        "type": "string",
                        "description": "Column name or partial name e.g. 'TotalGrossAmount' or 'gross' or 'CustomerID'"
                    }
                },
                "required": ["column_name"]
            }
        }
    },
]




def execute_tool(tool_name: str, tool_args: dict) -> str:
    try:
        if tool_name == "list_files":
            path = tool_args.get("directory_path", "/")
            context["current_folder"] = path
            return str(list_files(path))

        elif tool_name == "get_file_properties":
            fp = tool_args.get("file_path")
            context["last_file"] = fp
            return str(get_file_properties(fp))

        elif tool_name == "get_schema":
            fp = tool_args.get("file_path")
            context["last_file"] = fp
            return str(get_schema_tool(fp))

        elif tool_name == "duckdb_query":
            return str(duckdb_query(
                tool_args.get("sql"),
                export_excel=tool_args.get("export_excel", False)
            ))

        elif tool_name == "read_file":
            return str(read_file(tool_args.get("file_path")))

        elif tool_name == "search_file":
            result = str(search_file(tool_args.get("file_name")))
            import re
            paths = re.findall(r"Full Path\s*:\s*(.+)", result)
            if paths:
                context["last_file"] = paths[0].strip()
            return result

        elif tool_name == "search_column":          # ← NEW
            return str(search_column(tool_args.get("column_name")))

        else:
            return f"Unknown tool: {tool_name}"

    except Exception as e:
        import traceback
        return f"Error in {tool_name}: {str(e)}\n{traceback.format_exc()}"




def run():
    print("\n✅ Azure Data Lake Assistant — Ready!")
    print(f"   Model          : {MODEL}")
    print(f"   DuckDB         : ON (with SDK fallback)")
    print(f"   File Search    : ON (cached index)")
    print(f"   Column Search  : ON (NEW)")
    print(f"   Schema Cache   : ON")
    print("=" * 60)

    threading.Thread(target=build_file_index, daemon=True).start()

    print("Commands: 'history' | 'schema' | 'refresh' | 'clear' | 'exit'")
    print("=" * 60)

    conversation_history = [{"role": "system", "content": SYSTEM_PROMPT}]

    while True:
        user_input = input("\nYou: ").strip()

        if user_input.lower() in ["exit", "quit"]:
            print("Goodbye! 👋")
            break

        if user_input.lower() == "clear":
            conversation_history = [{"role": "system", "content": SYSTEM_PROMPT}]
            context["current_folder"] = "/"
            context["last_file"]      = None
            print("🧹 Memory cleared!")
            continue

        if user_input.lower() == "schema":
            print(list_schema_cache())
            continue

        if user_input.lower() == "refresh":
            print(refresh_file_index())
            continue

        if user_input.lower() == "history":
            print("\n📜 Conversation History:")
            print("-" * 40)
            for msg in conversation_history:
                if msg["role"] == "system":
                    continue
                role    = "You" if msg["role"] == "user" else "Assistant"
                content = msg.get("content") or "[tool call]"
                print(f"{role}: {str(content)[:200]}")
            print("-" * 40)
            continue

        if not user_input:
            continue

        context_hint = ""
        if context["current_folder"] != "/":
            context_hint += f" [Current folder: {context['current_folder']}]"
        if context["last_file"]:
            context_hint += f" [Last file: {context['last_file']}]"

        full_input = user_input + context_hint if context_hint else user_input
        conversation_history.append({"role": "user", "content": full_input})

        while True:

            if len(conversation_history) > 50:
                system_msg           = conversation_history[0]
                conversation_history = [system_msg] + conversation_history[-40:]

            for msg in conversation_history:
                if not isinstance(msg, dict):
                    continue
                if msg.get("role") == "tool":
                    content = msg.get("content", "")
                    if isinstance(content, str) and len(content) > 15000:
                        msg["content"] = content[:15000] + "\n[TRIMMED]"

            response = client.chat.completions.create(
                model=MODEL,
                messages=conversation_history,
                tools=TOOLS
            )

            message = response.choices[0].message

            conversation_history.append({
                "role":       message.role,
                "content":    message.content,
                "tool_calls": [
                    {
                        "id":       tc.id,
                        "type":     tc.type,
                        "function": {
                            "name":      tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    }
                    for tc in message.tool_calls
                ] if message.tool_calls else None
            })

            message = conversation_history[-1]

            if message.get("tool_calls"):
                for tool_call in message["tool_calls"]:
                    tool_name = tool_call["function"]["name"]
                    tool_args = json.loads(tool_call["function"]["arguments"])

                    print(f"\n⚙️  Calling: {tool_name}({tool_args})")

                    result_text = execute_tool(tool_name, tool_args)

                    if len(result_text) > 15000:
                        result_text = result_text[:15000] + "\n[TRIMMED]"

                    conversation_history.append({
                        "role":         "tool",
                        "tool_call_id": tool_call["id"],
                        "content":      result_text
                    })
            else:
                print(f"\n🤖 Assistant: {message.get('content')}")
                break


run()
