from dotenv import load_dotenv
import os

load_dotenv()
hash_val = os.getenv('ADMIN_PASSWORD_HASH')
print(f"Loaded Hash: '{hash_val}'")
print(f"Length: {len(hash_val) if hash_val else 0}")
if hash_val:
    print(f"Dollar count: {hash_val.count('$')}")
