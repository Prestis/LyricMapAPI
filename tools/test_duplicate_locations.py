import sys
import os

# Ensure we can load modules from the root
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal, init_db, Artist, Song, LocationMention
from sqlalchemy import func

def analyze_duplicates_in_db():
    db = SessionLocal()
    try:
        print("=== Analyzing Database for Location Name Duplicates ===")
        # Find all location names that appear more than once
        duplicates = db.query(
            LocationMention.location_name, 
            func.count(LocationMention.id).label('count')
        ).group_by(LocationMention.location_name)\
         .having(func.count(LocationMention.id) > 1)\
         .all()
         
        if not duplicates:
            print("No duplicate location names found in the database yet.")
            return

        print(f"Found {len(duplicates)} location names with duplicate mentions.\n")
        
        for loc_name, count in duplicates:
            print(f"Location: '{loc_name}' (Mentioned {count} times)")
            
            # Fetch all mentions of this location
            mentions = db.query(LocationMention).filter(
                LocationMention.location_name == loc_name
            ).all()
            
            # Group by coordinates to see if they differ
            coords_set = set()
            for m in mentions:
                # Get song and artist info
                song = db.query(Song).filter(Song.id == m.song_id).first()
                artist = db.query(Artist).filter(Artist.id == song.artist_id).first() if song else None
                artist_name = artist.name if artist else "Unknown Artist"
                song_title = song.title if song else "Unknown Song"
                
                coords_set.add((m.lat, m.lng))
                print(f"  - Mention in '{song_title}' by '{artist_name}': lat={m.lat}, lng={m.lng}, is_manual={m.is_manual}")
                
            if len(coords_set) == 1:
                print(f"  👉 RESULT: All mentions share the EXACT SAME coordinates. (Cached/Duplicated)\n")
            else:
                print(f"  👉 RESULT: Mentions have DIFFERENT coordinates! (Differentiated/Manually updated) ({len(coords_set)} unique sets of coordinates)\n")
                
    except Exception as e:
        print(f"Error analyzing database: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    analyze_duplicates_in_db()
