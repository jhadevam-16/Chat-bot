import os
import re
import io
import time
import logging
import threading as _threading
import pandas as pd
from dotenv import load_dotenv

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

load_dotenv()

ACCOUNT_NAME = os.getenv("AZURE_STORAGE_ACCOUNT_NAME")
ACCOUNT_KEY  = os.getenv("AZURE_STORAGE_ACCOUNT_KEY")
CONTAINER    = os.getenv("AZURE_CONTAINER_NAME")

AZURE_CONN_STR = (
    f"DefaultEndpointsProtocol=https;"
    f"AccountName={ACCOUNT_NAME};"
    f"AccountKey={ACCOUNT_KEY};"
    f"EndpointSuffix=core.windows.net"
)

# ════════════════════════════════════════════════════════════
# AZURE SDK HELPERS
# ════════════════════════════════════════════════════════════

def get_azure_file_client(file_path: str):
    from azure.storage.filedatalake import DataLakeServiceClient
    file_path = file_path.lstrip("/")
    svc = DataLakeServiceClient(
        account_url=f"https://{ACCOUNT_NAME}.dfs.core.windows.net",
        credential=ACCOUNT_KEY
    )
    return svc.get_file_system_client(CONTAINER).get_file_client(file_path)


def download_as_dataframe(file_path: str) -> pd.DataFrame:
    file_path = file_path.lstrip("/")
    fc   = get_azure_file_client(file_path)
    data = fc.download_file().readall()
    ext  = file_path.split(".")[-1].lower()
    if ext == "parquet":
        return pd.read_parquet(io.BytesIO(data))
    elif ext == "csv":
        return pd.read_csv(io.BytesIO(data))
    elif ext == "xlsx":
        return pd.read_excel(io.BytesIO(data))
    else:
        raise ValueError(f"Unsupported file type: {ext}")



_duck_con    = None
_duck_failed = False


def get_duck_con():
    global _duck_con, _duck_failed
    if _duck_failed:
        raise RuntimeError("DuckDB previously failed — using SDK fallback.")
    if _duck_con is not None:
        return _duck_con
    try:
        import duckdb
        con = duckdb.connect()
        con.execute("INSTALL azure; LOAD azure;")
        con.execute(f"SET azure_storage_connection_string = '{AZURE_CONN_STR}';")
        con.execute("SET http_keep_alive = false;")
        _duck_con = con
        logger.debug("DuckDB connected successfully")
        return con
    except Exception as e:
        _duck_failed = True
        raise RuntimeError(f"DuckDB init failed: {str(e)}")




_schema_cache: dict = {}


def get_schema(file_path: str) -> dict:
    file_path = file_path.lstrip("/")
    if file_path in _schema_cache:
        return _schema_cache[file_path]

    try:
        con     = get_duck_con()
        path    = f"azure://{CONTAINER}/{file_path}"
        desc_df = con.execute(f"DESCRIBE SELECT * FROM '{path}'").df()
        columns = desc_df["column_name"].tolist()
        dtypes  = desc_df["column_type"].tolist()
        schema  = {
            "columns": columns,
            "dtypes":  dict(zip(columns, dtypes)),
            "source":  "duckdb"
        }
        _schema_cache[file_path] = schema
        return schema
    except Exception as duck_err:
        logger.warning(f"DuckDB schema failed: {duck_err}")

    try:
        print(f"   ⚠️  DuckDB unavailable, using SDK fallback...", flush=True)
        ext  = file_path.split(".")[-1].lower()
        fc   = get_azure_file_client(file_path)
        data = fc.download_file().readall()

        if ext == "parquet":
            df = pd.read_parquet(io.BytesIO(data))
        elif ext == "csv":
            df = pd.read_csv(io.BytesIO(data), nrows=0)
        else:
            df = pd.read_excel(io.BytesIO(data), nrows=0)

        schema = {
            "columns": list(df.columns),
            "dtypes":  {c: str(df[c].dtype) for c in df.columns},
            "rows":    len(df),
            "source":  "sdk_fallback"
        }
        _schema_cache[file_path] = schema
        return schema

    except Exception as sdk_err:
        return {
            "columns": [],
            "dtypes":  {},
            "error":   f"DuckDB: {duck_err} | SDK: {sdk_err}"
        }


def list_schema_cache() -> str:
    if not _schema_cache:
        return "No schemas cached yet."
    out = "CACHED SCHEMAS\n" + "═" * 40 + "\n"
    for path, info in _schema_cache.items():
        out += f"\n{path} [{info.get('source','')}]\n"
        out += f"  Columns ({len(info.get('columns', []))}) : {info.get('columns', [])}\n"
    return out




def list_files(directory_path: str = "/"):
    try:
        from azure.storage.filedatalake import DataLakeServiceClient
        svc = DataLakeServiceClient(
            account_url=f"https://{ACCOUNT_NAME}.dfs.core.windows.net",
            credential=ACCOUNT_KEY
        )
        fs         = svc.get_file_system_client(CONTAINER)
        azure_path = "" if directory_path in ["/", "", None] else directory_path.lstrip("/")
        paths      = fs.get_paths(path=azure_path, recursive=False)

        files, folders = [], []
        for path in paths:
            if path.is_directory:
                folders.append(f"📁 {path.name}/")
            else:
                ext        = path.name.split(".")[-1].upper() if "." in path.name else "FILE"
                size_bytes = path.content_length or 0
                if size_bytes < 1024:
                    size_str = f"{size_bytes} B"
                elif size_bytes < 1024 * 1024:
                    size_str = f"{size_bytes / 1024:.1f} KB"
                elif size_bytes < 1024 * 1024 * 1024:
                    size_str = f"{size_bytes / (1024 * 1024):.1f} MB"
                else:
                    size_str = f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"
                files.append(f"📄 [{ext}] {path.name} ({size_str})")

        result = f"Contents of '{directory_path}':\n" + "═" * 40 + "\n"
        if folders:
            result += f"\n📁 FOLDERS ({len(folders)}):\n" + "".join(f"  {f}\n" for f in folders)
        if files:
            result += f"\n📄 FILES ({len(files)}):\n" + "".join(f"  {f}\n" for f in files)
        if not folders and not files:
            result += "  No files or folders found.\n"
        result += f"\nTotal: {len(folders)} folder(s), {len(files)} file(s)"
        result += "\nTip: Ask me to explore any folder or query any file."
        return result

    except Exception as e:
        import traceback
        return f"Error listing files: {str(e)} | {traceback.format_exc()}"




def get_file_properties(file_path: str) -> str:
    try:
        file_path  = file_path.lstrip("/")
        fc         = get_azure_file_client(file_path)
        props      = fc.get_file_properties()
        size_bytes = props.size

        if size_bytes < 1024:
            size_str = f"{size_bytes} B"
        elif size_bytes < 1024 ** 2:
            size_str = f"{size_bytes / 1024:.2f} KB"
        elif size_bytes < 1024 ** 3:
            size_str = f"{size_bytes / 1024 ** 2:.2f} MB"
        else:
            size_str = f"{size_bytes / 1024 ** 3:.2f} GB"

        ext         = file_path.split(".")[-1].upper()
        schema_info = ""
        if ext in ["PARQUET", "CSV"]:
            schema = get_schema(file_path)
            if schema.get("columns"):
                schema_info = (
                    f"\nColumns ({len(schema['columns'])}) : {schema['columns']}"
                    f"\n(Source: {schema.get('source', 'unknown')})"
                )

        return f"""FILE PROPERTIES

Name          : {file_path}
Size          : {size_str} ({size_bytes:,} bytes)
Last Modified : {props.last_modified}
File Type     : {ext}{schema_info}"""

    except Exception as e:
        import traceback
        return f"Error getting properties: {str(e)} | {traceback.format_exc()}"




def get_schema_tool(file_path: str) -> str:
    file_path = file_path.lstrip("/")
    schema    = get_schema(file_path)

    if schema.get("error"):
        return f"❌ Could not fetch schema:\n{schema['error']}"

    cols      = schema["columns"]
    dtypes    = schema.get("dtypes", {})
    source    = schema.get("source", "unknown")
    col_lines = "\n".join(f"  {c:<45} {dtypes.get(c,'')}" for c in cols)

    return (
        f"SCHEMA: {file_path}  [{source}]\n"
        + "═" * 55 + "\n"
        + f"Total columns : {len(cols)}\n\n"
        + f"{'Column':<45} {'Type'}\n"
        + "─" * 55 + "\n"
        + col_lines
    )




def _format_query_result(df, elapsed, sql_resolved, export_excel, note=""):
    if df.empty:
        return f"✅ Query ran in {elapsed:.1f}s — 0 rows returned."

    rows, cols = df.shape

    az_paths = re.findall(
        r"azure://[^/]+/([^\s'\"]+\.(?:parquet|csv))",
        sql_resolved, re.IGNORECASE
    )
    for p in az_paths:
        if p not in _schema_cache and not df.empty:
            _schema_cache[p] = {
                "columns":   list(df.columns),
                "dtypes":    {c: str(df[c].dtype) for c in df.columns},
                "row_count": rows,
                "source":    "query_result"
            }

    def truncate(val, n=60):
        s = str(val) if not (isinstance(val, float) and pd.isna(val)) else ""
        return s[:n] + "…" if len(s) > n else s

    display_df = df.head(50).copy()
    for col in display_df.columns:
        display_df[col] = display_df[col].apply(truncate)

    col_map = {}
    seen    = set()
    for c in display_df.columns:
        clean = re.sub(r'_\d+$', '', c)
        if clean in seen:
            col_map[c] = f"{clean}(2)"
        else:
            seen.add(clean)
            if clean != c:
                col_map[c] = clean
    display_df = display_df.rename(columns=col_map)

    output  = f"✅ {rows:,} rows × {cols} columns  ({elapsed:.1f}s)"
    if note:
        output += f"\n{note}"
    output += "\n" + "─" * 50 + "\n"

    if cols > 8:
        output += f"Wide result ({cols} cols) — showing first 5 rows vertically:\n\n"
        for i, (_, row) in enumerate(display_df.head(5).iterrows()):
            output += f"── Row {i + 1} " + "─" * 32 + "\n"
            for col_name, val in row.items():
                output += f"  {str(col_name):<30} : {val}\n"
            output += "\n"
    else:
        pd.set_option("display.max_colwidth", 60)
        pd.set_option("display.width", 200)
        output += display_df.to_string(index=False) + "\n"

    if rows > 50:
        output += f"\n... {rows - 50:,} more rows not shown."

    if export_excel:
        desktop = os.path.join(
            os.path.expanduser("~"),
            "OneDrive - Vaibhav Global Limited", "Desktop"
        )
        if not os.path.exists(desktop):
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        filename  = f"query_result_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        save_path = os.path.join(desktop, filename)
        df.to_excel(save_path, index=False)
        output += f"\n\n📥 Saved to Desktop: {filename}"

    if len(output) > 10000:
        output = output[:10000] + "\n\n⚠️ Output capped. Ask to export to Excel for full data."

    return output


def duckdb_query(sql: str, export_excel: bool = False) -> str:

    def replace_az(match):
        raw   = match.group(1)
        parts = raw.split("/", 1)
        path  = parts[1] if parts[0] == CONTAINER and len(parts) > 1 else raw
        return f"'azure://{CONTAINER}/{path}'"

    sql_resolved = re.sub(r"'az://([^']+)'", replace_az, sql)

    try:
        print(f"   ⚡ DuckDB querying Azure directly...", flush=True)
        t_start = time.time()
        con     = get_duck_con()

        df         = None
        last_error = None
        for attempt in range(2):
            try:
                df = con.execute(sql_resolved).df()
                break
            except Exception as e:
                last_error = str(e)
                if attempt == 0:
                    sql_resolved = re.sub(
                        r"azure://([^/]+)//",
                        lambda m: f"azure://{m.group(1)}/",
                        sql_resolved
                    )
                    print(f"   ⚠️  Retrying query...", flush=True)

        if df is None:
            raise Exception(last_error)

        elapsed = time.time() - t_start
        print(f"   ✅ Done in {elapsed:.1f}s", flush=True)
        return _format_query_result(df, elapsed, sql_resolved, export_excel)

    except Exception as duck_err:
        logger.warning(f"DuckDB query failed: {duck_err}")

    try:
        print(f"   ⚠️  DuckDB failed, trying SDK fallback...", flush=True)

        paths_found = re.findall(
            r"azure://[^/]+/([^\s'\"]+\.(?:parquet|csv|xlsx))",
            sql_resolved, re.IGNORECASE
        )
        if not paths_found:
            paths_found = re.findall(
                r"az://[^/]+/([^\s'\"]+\.(?:parquet|csv|xlsx))",
                sql, re.IGNORECASE
            )

        if not paths_found:
            return f"❌ DuckDB failed and could not find file path in SQL.\nError: {duck_err}"

        file_path = paths_found[0]
        t_start   = time.time()
        df        = download_as_dataframe(file_path)
        elapsed   = time.time() - t_start
        print(f"   ✅ SDK loaded {len(df):,} rows in {elapsed:.1f}s", flush=True)

        sql_upper = sql.upper()
        if "COUNT(*)" in sql_upper:
            return f"✅ Row count: {len(df):,}  ({elapsed:.1f}s)"

        limit       = 50
        limit_match = re.search(r"LIMIT\s+(\d+)", sql_upper)
        if limit_match:
            limit = int(limit_match.group(1))

        result_df = df.head(limit)
        return _format_query_result(
            result_df, elapsed, file_path, export_excel,
            note="⚠️ via SDK fallback — showing first rows only"
        )

    except Exception as sdk_err:
        import traceback
        return (
            f"❌ Both DuckDB and SDK failed.\n"
            f"DuckDB: {duck_err}\n"
            f"SDK: {sdk_err}\n"
            f"{traceback.format_exc()}"
        )




def read_file(file_path: str) -> str:
    try:
        file_path = file_path.lstrip("/")
        fc        = get_azure_file_client(file_path)
        props     = fc.get_file_properties()
        if props.size > 100_000:
            return (
                f"⚠️ File is {props.size / 1024:.0f} KB — too large for read_file. "
                "Use duckdb_query instead."
            )
        data = fc.download_file().readall()
        text = data.decode("utf-8", errors="replace")
        if len(text) > 8000:
            text = text[:8000] + f"\n\n⚠️ Truncated — {len(text):,} chars total."
        return text
    except Exception as e:
        import traceback
        return f"Error reading file: {str(e)} | {traceback.format_exc()}"


# ════════════════════════════════════════════════════════════
# FILE INDEX — Built once, instant search
# ════════════════════════════════════════════════════════════

_file_index:       list = []
_file_index_built: bool = False
_index_lock              = _threading.Lock()


def build_file_index():
    global _file_index, _file_index_built

    with _index_lock:
        if _file_index_built:
            return
        try:
            from azure.storage.filedatalake import DataLakeServiceClient
            print("   📂 Building file index...", flush=True)
            svc = DataLakeServiceClient(
                account_url=f"https://{ACCOUNT_NAME}.dfs.core.windows.net",
                credential=ACCOUNT_KEY
            )
            fs        = svc.get_file_system_client(CONTAINER)
            all_paths = fs.get_paths(path="", recursive=True)

            index = []
            for path in all_paths:
                if path.is_directory:
                    continue
                size_bytes = path.content_length or 0
                if size_bytes < 1024:
                    size_str = f"{size_bytes} B"
                elif size_bytes < 1024 * 1024:
                    size_str = f"{size_bytes / 1024:.1f} KB"
                elif size_bytes < 1024 * 1024 * 1024:
                    size_str = f"{size_bytes / (1024 * 1024):.1f} MB"
                else:
                    size_str = f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"

                index.append({
                    "full_path": path.name,
                    "file_name": path.name.split("/")[-1],
                    "folder":    "/".join(path.name.split("/")[:-1]),
                    "size":      size_str,
                })

            _file_index       = index
            _file_index_built = True
            print(f"   ✅ File index built — {len(index)} files cached.", flush=True)

        except Exception as e:
            print(f"   ⚠️  File index failed: {e}", flush=True)


def search_file(file_name: str) -> str:
    if not _file_index_built:
        build_file_index()

    def normalize(s):
        return re.sub(r'[\s_\-]+', '', s).lower()

    search_norm = normalize(file_name)
    keywords    = [w.lower() for w in re.split(r'[\s_\-]+', file_name.strip()) if w]

    matches = []
    seen    = set()

    for f in _file_index:
        name_only        = f["file_name"].lower()
        name_no_ext      = name_only.rsplit(".", 1)[0]
        name_norm        = normalize(name_only)
        name_no_ext_norm = normalize(name_no_ext)
        all_kw_match     = all(k in name_no_ext for k in keywords)

        if (search_norm in name_norm or
            search_norm in name_no_ext_norm or
            name_no_ext_norm in search_norm or
            all_kw_match):
            if f["full_path"] not in seen:
                matches.append(f)
                seen.add(f["full_path"])

    if not matches:
        for f in _file_index:
            name_no_ext = f["file_name"].lower().rsplit(".", 1)[0]
            if any(k in name_no_ext for k in keywords if len(k) > 3):
                if f["full_path"] not in seen:
                    matches.append(f)
                    seen.add(f["full_path"])

    if not matches:
        return (
            f"❌ No file found matching '{file_name}'.\n"
            f"Tried keywords: {keywords}\n"
            f"Try a shorter keyword like 'salesorder' or 'orderline'."
        )

    result  = f"🔍 SEARCH RESULTS for '{file_name}'\n"
    result += "═" * 50 + "\n"
    result += f"Found {len(matches)} match(es):\n\n"
    for i, m in enumerate(matches, 1):
        result += f"{i}. {m['file_name']} ({m['size']})\n"
        result += f"   📁 Folder    : {m['folder']}\n"
        result += f"   📄 Full Path : {m['full_path']}\n\n"
    result += "─" * 50 + "\n"
    result += "✅ Use the Full Path above to query or read the file."
    return result


def refresh_file_index() -> str:
    global _file_index_built
    _file_index_built = False
    build_file_index()
    return f"✅ File index refreshed — {len(_file_index)} files indexed."




def search_column(column_name: str) -> str:
    """
    Searches for a column name across ALL files in the Data Lake.
    Checks cached schemas first (instant), then scans remaining files.
    """
    if not _file_index_built:
        build_file_index()

    search_term = column_name.strip().lower()
    search_norm = re.sub(r'[\s_\-]+', '', search_term)

    # ── Step 1: Check already cached schemas (instant) ────────
    cached_matches = []
    for file_path, schema in _schema_cache.items():
        for col in schema.get("columns", []):
            col_norm = re.sub(r'[\s_\-]+', '', col.lower())
            if search_term in col.lower() or search_norm in col_norm:
                cached_matches.append({
                    "file":   file_path,
                    "column": col,
                    "dtype":  schema.get("dtypes", {}).get(col, ""),
                    "source": "cached"
                })
                break  # one match per file

    if cached_matches:
        result  = f"🔍 COLUMN SEARCH — '{column_name}'\n"
        result += "═" * 55 + "\n"
        result += f"Found in {len(cached_matches)} cached file(s):\n\n"
        for i, m in enumerate(cached_matches, 1):
            result += f"{i}. {m['file'].split('/')[-1]}\n"
            result += f"   Column    : {m['column']}  ({m['dtype']})\n"
            result += f"   Full Path : {m['file']}\n\n"
        result += "─" * 55 + "\n"
        result += "✅ Use the full path above with duckdb_query to analyze this column.\n"
        result += "ℹ️  Only cached schemas were checked. Type 'search_column' again after more files are queried for broader results."
        return result


    print(f"   🔍 Scanning all schemas for column '{column_name}'...", flush=True)

    data_files  = [
        f for f in _file_index
        if f["file_name"].lower().endswith((".parquet", ".csv"))
    ]
    matches     = []
    scanned     = 0
    total_files = len(data_files)

    for f in data_files:
        file_path = f["full_path"]
        scanned  += 1

        if scanned % 20 == 0:
            print(f"   🔍 Scanning {scanned}/{total_files}...", flush=True)

        schema = get_schema(file_path)

        for col in schema.get("columns", []):
            col_norm = re.sub(r'[\s_\-]+', '', col.lower())
            if search_term in col.lower() or search_norm in col_norm:
                matches.append({
                    "file":   file_path,
                    "column": col,
                    "dtype":  schema.get("dtypes", {}).get(col, ""),
                    "folder": f["folder"]
                })
                break  # one match per file

    print(f"   ✅ Scanned {scanned} files.", flush=True)

    if not matches:
        return (
            f"❌ Column '{column_name}' not found in any file.\n"
            f"Scanned {scanned} files.\n"
            f"Try a shorter keyword e.g. 'gross' instead of 'TotalGrossAmount'."
        )

    result  = f"🔍 COLUMN SEARCH — '{column_name}'\n"
    result += "═" * 55 + "\n"
    result += f"Found in {len(matches)} file(s) (scanned {scanned} total):\n\n"
    for i, m in enumerate(matches, 1):
        result += f"{i}. {m['file'].split('/')[-1]}\n"
        result += f"   Column    : {m['column']}  ({m['dtype']})\n"
        result += f"   Full Path : {m['file']}\n\n"
    result += "─" * 55 + "\n"
    result += "✅ Use the full path above with duckdb_query to analyze this column."
    return result
