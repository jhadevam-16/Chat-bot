from dotenv import load_dotenv
import os
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

try:
    import duckdb
    print("✅ DuckDB imported")

    con = duckdb.connect()
    print("✅ DuckDB connected")

    con.execute("INSTALL azure; LOAD azure;")
    print("✅ Azure extension loaded")

    con.execute(f"SET azure_storage_connection_string = '{AZURE_CONN_STR}';")
    print("✅ Connection string set")

    # Test query
    path = f"azure://{CONTAINER}/shoplc/order-management-system/sales/Sales_SalesOrderlines.parquet"
    print(f"\n🔍 Testing path: {path}")

    result = con.execute(f"DESCRIBE SELECT * FROM '{path}'").df()
    print("✅ Schema fetched!")
    print(result)

except Exception as e:
    import traceback
    print(f"❌ Error: {e}")
    print(traceback.format_exc())