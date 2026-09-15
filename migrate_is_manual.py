import sqlite3
import os

db_path = "lyricmap.db"

if not os.path.exists(db_path):
    print(f"Error: Database file {db_path} not found.")
    exit(1)

try:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Check if column already exists
    cursor.execute("PRAGMA table_info(location_mentions)")
    columns = [row[1] for row in cursor.fetchall()]
    
    if "is_manual" not in columns:
        print("Adding 'is_manual' column to 'location_mentions' table...")
        cursor.execute("ALTER TABLE location_mentions ADD COLUMN is_manual BOOLEAN DEFAULT 0")
        conn.commit()
        print("Column added successfully.")
    else:
        print("Column 'is_manual' already exists.")
        
    conn.close()
except Exception as e:
    print(f"Error during migration: {e}")
    if 'conn' in locals():
        conn.close()
