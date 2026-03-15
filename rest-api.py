import lyricsgenius
from dotenv import load_dotenv
import os
from transformers import AutoTokenizer, AutoModelForTokenClassification, pipeline
from fastapi import FastAPI, BackgroundTasks, Depends, HTTPException
from google import genai 
from google.genai import types
import time 
import csv
import json
import threading
from fastapi.middleware.cors import CORSMiddleware
import datetime
from typing import List, Optional, Dict
from pydantic import BaseModel
from sqlalchemy.orm import Session
from database import get_db, init_db, Artist, Song, LocationMention, ApiUsage, SessionLocal

# Load environment variables
load_dotenv()
GENIUS_TOKEN = os.getenv('GENIUS_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
MAX_DAILY_REQUESTS = 10000 

# Load Greek NER pipeline
model_name = "Davlan/xlm-roberta-base-ner-hrl"
tokenizer = AutoTokenizer.from_pretrained(model_name)
model = AutoModelForTokenClassification.from_pretrained(model_name)
ner_pipeline = pipeline("ner", model=model, tokenizer=tokenizer, aggregation_strategy="simple")

# Initialize Database
init_db()

from fastapi.responses import JSONResponse

class UnicodeJSONResponse(JSONResponse):
    def render(self, content: any) -> bytes:
        return json.dumps(
            content,
            ensure_ascii=False,
            allow_nan=False,
            indent=None,
            separators=(",", ":"),
        ).encode("utf-8")

app = FastAPI(title="LyricMap API", default_response_class=UnicodeJSONResponse)

# Response Models
class LocationResponse(BaseModel):
    location: str
    song: str
    lat: Optional[float]
    lng: Optional[float]

    class Config:
        from_attributes = True

class ArtistLocationsResponse(BaseModel):
    artist: str
    mentions: List[LocationResponse]

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200"], # Or ["*"] for dev
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_api_usage(db: Session):
    today = datetime.date.today()
    usage = db.query(ApiUsage).filter(ApiUsage.date == today).first()
    if not usage:
        usage = ApiUsage(date=today, count=0)
        db.add(usage)
        db.commit()
    return usage

def update_api_usage(db: Session, usage: ApiUsage):
    usage.count += 1
    db.commit()

def extract_locations_from_entities(chunk_text, entities, min_score=0.85):
    locations = []
    current_start = None
    current_end = None

    for ent in entities:
        if ent['entity_group'] == 'LOC' and ent['score'] >= min_score:
            if current_end is not None and ent['start'] <= current_end + 1:
                current_end = max(current_end, ent['end'])
            else:
                if current_start is not None:
                    loc_str = chunk_text[current_start:current_end].strip()
                    if len(loc_str) > 2 and not loc_str.isupper():
                        locations.append(loc_str)
                current_start = ent['start']
                current_end = ent['end']

    if current_start is not None:
        loc_str = chunk_text[current_start:current_end].strip()
        if len(loc_str) > 2 and not loc_str.isupper():
            locations.append(loc_str)

    return list(set(locations))

def extract_locations_ner(text, chunk_size=450):
    words = text.split()
    chunks = [' '.join(words[i:i + chunk_size]) for i in range(0, len(words), chunk_size)]
    locations = set()
    for chunk in chunks:
        entities = ner_pipeline(chunk)
        chunk_locations = extract_locations_from_entities(chunk, entities)
        locations.update(chunk_locations)
    return list(locations)

def get_coordinates(location_name, artist_context, db: Session):
    # Init Gemini API
    client = genai.Client(api_key=GEMINI_API_KEY) 
    # 1. CHECK FOR DUPLICATES FIRST
    # Query database for existing location with coordinates
    existing = db.query(LocationMention).filter(
        LocationMention.location_name == location_name.lower(),
        LocationMention.lat.isnot(None)
    ).first()
    
    if existing:
        return {"lat": existing.lat, "lng": existing.lng, "status": "cached"}

    # 2. CHECK DAILY LIMIT
    usage = get_api_usage(db)
    if usage.count >= MAX_DAILY_REQUESTS:
        return "LIMIT_REACHED"

    # 3. CALL API (Stay within 15 RPM = 4s sleep)
    time.sleep(4)

    if not GEMINI_API_KEY:
        return {"lat": None, "lng": None}

    prompt = f"""
    The Greek rapper '{artist_context}' mentioned the location '{location_name}' in a song.
    Provide the approximate latitude and longitude for this location.
    This location could be anywhere in the world, so don't dismiss famous locations from other countries.
    Take into account where the rapper is from/based when analysing Greek locations.
    Return ONLY a JSON object with the following keys: "lat", "lng" and float values.
    If the location is unknown or fictional, return null for the values.
    """
    try:
        # The new SDK uses a more streamlined response format
        response = client.models.generate_content(
            model='gemini-3.1-flash-lite-preview',
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type='application/json', # Forces JSON output
            )
        )
        update_api_usage(db, usage)

        result = json.loads(response.text)
        
        # Ensure we return a dictionary even if the model returns a list
        if isinstance(result, list):
            if len(result) > 0:
                result = result[0]
            else:
                return {"lat": None, "lng": None}
        
        if not isinstance(result, dict):
             return {"lat": None, "lng": None}

        return result
    except Exception as e:
        print(f"Gemini API Error: {e}")
        return {"lat": None, "lng": None}

def process_artist_task(artist_name: str):
    print(f"\n--- Background processing artist: {artist_name} ---")
    db = SessionLocal()
    # Init Genius API
    genius = lyricsgenius.Genius(GENIUS_TOKEN)

    try:
        artist_obj = db.query(Artist).filter(Artist.name == artist_name).first()
        if not artist_obj:
            artist_obj = Artist(name=artist_name)
            db.add(artist_obj)
            db.commit()
            db.refresh(artist_obj)

        artist = genius.search_artist(artist_name, max_songs=20, sort="popularity")
        if artist:
            for song in artist.songs:
                # Check if song exists
                song_obj = db.query(Song).filter(Song.artist_id == artist_obj.id, Song.title == song.title).first()
                if song_obj and song_obj.is_processed:
                    print(f"  [SKIP] {song.title} (already processed)")
                    continue
                
                if not song_obj:
                    song_obj = Song(artist_id=artist_obj.id, title=song.title)
                    db.add(song_obj)
                    db.commit()
                    db.refresh(song_obj)

                print(f"  [PROCESS] {song.title}")
                if hasattr(song, 'lyrics') and song.lyrics:
                    song_locations = extract_locations_ner(song.lyrics)
                    
                    for loc in song_locations:
                        try:
                            # Pass db session to get_coordinates
                            coords = get_coordinates(loc, artist_name, db)
                            
                            if coords == "LIMIT_REACHED":
                                print(f"!!! Breakpoint: Daily quota reached. Stopping.")
                                return

                            # Ensure coords is a dict
                            if not isinstance(coords, dict):
                                coords = {"lat": None, "lng": None}

                            # Add location mention if not already exists for this song
                            existing_mention = db.query(LocationMention).filter(
                                LocationMention.song_id == song_obj.id,
                                LocationMention.location_name == loc.lower()
                            ).first()
                            
                            if not existing_mention:
                                new_mention = LocationMention(
                                    song_id=song_obj.id,
                                    location_name=loc.lower(),
                                    lat=coords.get("lat"),
                                    lng=coords.get("lng")
                                )
                                db.add(new_mention)
                                db.commit()

                            # (15 RPM = 1 call every 4 seconds)
                            time.sleep(4)
                        except Exception as loc_e:
                            print(f"  [ERROR] Failed to process location '{loc}': {loc_e}")
                            db.rollback()
                            continue
                    
                    song_obj.is_processed = True
                    db.commit()
            
            print(f"--- Finished updating {artist_name} ---")
        else:
            print(f"--- Artist {artist_name} not found ---")
            
    except Exception as e:
        print(f"--- Error processing {artist_name}: {e} ---")
        db.rollback()
    finally:
        db.close()

@app.get("/locations", response_model=List[ArtistLocationsResponse])
def get_locations(db: Session = Depends(get_db)):
    """Expose the rappers locations from the database."""
    artists = db.query(Artist).all()
    response = []
    
    for artist in artists:
        mentions = []
        for song in artist.songs:
            for mention in song.locations:
                mentions.append(LocationResponse(
                    location=mention.location_name,
                    song=song.title,
                    lat=mention.lat,
                    lng=mention.lng
                ))
        
        if mentions:
            response.append(ArtistLocationsResponse(
                artist=artist.name,
                mentions=mentions
            ))
            
    return response

@app.post("/process-all")
def trigger_all_processing(background_tasks: BackgroundTasks):
    """Trigger processing for all artists in the CSV file."""
    artists_list = []
    if os.path.exists("Greek-Rappers-Genius-API.csv"):
        with open("Greek-Rappers-Genius-API.csv", "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            try:
                next(reader)  # Skip header
                for row in reader:
                    if len(row) >= 2:
                        artists_list.append(row[1].strip())
            except StopIteration:
                pass
    
    for artist in artists_list:
        background_tasks.add_task(process_artist_task, artist)
    
    return {"message": "Processing started in background for all artists."}

@app.post("/process/{artist_name}")
def trigger_artist_processing(artist_name: str, background_tasks: BackgroundTasks):
    """Trigger processing for a specific artist."""
    background_tasks.add_task(process_artist_task, artist_name)
    return {"message": f"Processing started in background for {artist_name}."}

if __name__ == "__main__":
    import uvicorn
    # Start the server
    uvicorn.run(app, host="0.0.0.0", port=8000)


