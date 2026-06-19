from dotenv import load_dotenv
import os
from azure.storage.filedatalake import DataLakeServiceClient

load_dotenv()

ACCOUNT_NAME = os.getenv("AZURE_STORAGE_ACCOUNT_NAME")
ACCOUNT_KEY = os.getenv("AZURE_STORAGE_ACCOUNT_KEY")
CONTAINER = os.getenv("AZURE_CONTAINER_NAME")

print(f"Account: {ACCOUNT_NAME}")
print(f"Container: {CONTAINER}")

try:
    account_url = f"https://{ACCOUNT_NAME}.dfs.core.windows.net"
    
    service_client = DataLakeServiceClient(
        account_url=account_url,
        credential=ACCOUNT_KEY
    )
    
    file_system_client = service_client.get_file_system_client(CONTAINER)
    paths = file_system_client.get_paths(path="/")
    
    print("\n✅ Files found:")
    for path in paths:
        print(f"  - {path.name}")
        
except Exception as e:
    print(f"\n❌ Full Error: {e}")