import json
import os
import datetime
from database import SessionLocal, init_db, Artist, Song, LocationMention, ApiUsage

# File paths
LOCATIONS_FILE = "rappers_locations.json"
PROCESSED_SONGS_FILE = "processed_songs.json"
USAGE_STATS_FILE = "api_usage.json"

def load_json(file_path, default_val):
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default_val
    return default_val

def migrate():
    # Initialize DB (create tables)
    init_db()
    db = SessionLocal()

    print("Starting migration...")

    # 1. Migrate Processed Songs
    processed_songs_keys = load_json(PROCESSED_SONGS_FILE, [])
    # keys are: "artist_name|song_title"
    
    # 2. Migrate Rappers Locations
    locations_data = load_json(LOCATIONS_FILE, {})
    
    for artist_name, entries in locations_data.items():
        # Get or create artist
        artist = db.query(Artist).filter(Artist.name == artist_name).first()
        if not artist:
            artist = Artist(name=artist_name)
            db.add(artist)
            db.flush() # Get artist.id
        
        for entry in entries:
            song_title = entry.get("song")
            if not song_title:
                continue
                
            # Get or create song
            song = db.query(Song).filter(Song.artist_id == artist.id, Song.title == song_title).first()
            if not song:
                song_key = f"{artist_name}|{song_title}".strip().lower()
                is_processed = song_key in processed_songs_keys
                song = Song(artist_id=artist.id, title=song_title, is_processed=is_processed)
                db.add(song)
                db.flush()
            
            # Add location mention
            location = LocationMention(
                song_id=song.id,
                location_name=entry.get("location"),
                lat=entry.get("lat"),
                lng=entry.get("lng")
            )
            db.add(location)

    # 3. Migrate API Usage
    usage_data = load_json(USAGE_STATS_FILE, {})
    if usage_data:
        date_str = usage_data.get("date")
        count = usage_data.get("count", 0)
        if date_str:
            try:
                usage_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
                usage = ApiUsage(date=usage_date, count=count)
                db.add(usage)
            except Exception as e:
                print(f"Error parsing date {date_str}: {e}")

    try:
        db.commit()
        print("Migration completed successfully!")
    except Exception as e:
        db.rollback()
        print(f"Migration failed: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    migrate()
