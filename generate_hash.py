from passlib.context import CryptContext
import sys

def generate_hash():
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    
    if len(sys.argv) > 1:
        password = sys.argv[1]
    else:
        password = input("Enter the password to hash: ")
        
    hashed = pwd_context.hash(password)
    print("\n--- NEW BCRYPT HASH ---")
    print(hashed)
    print("------------------------\n")
    print("Copy the hash above and paste it into rest-api.py in the ADMIN_PASSWORD_HASH variable.")

if __name__ == "__main__":
    try:
        generate_hash()
    except KeyboardInterrupt:
        print("\nOperation cancelled.")
    except Exception as e:
        print(f"Error: {e}")
