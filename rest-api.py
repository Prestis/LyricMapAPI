import lyricsgenius
from dotenv import load_dotenv
import os
from gr_nlp_toolkit import Pipeline
from fastapi import FastAPI, BackgroundTasks, Depends, HTTPException, Request, Response, Cookie
from google import genai 
from google.genai import types
import time 
import csv
import json
import threading
from fastapi.middleware.cors import CORSMiddleware
import datetime
from typing import List, Optional, Dict, Annotated
from pydantic import BaseModel
from sqlalchemy.orm import Session
from database import get_db, init_db, Artist, Song, LocationMention, ApiUsage, SessionLocal, Report
from passlib.context import CryptContext
from jose import JWTError, jwt
from fastapi.security import OAuth2PasswordRequestForm
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
# Load environment variables
load_dotenv()
GENIUS_TOKEN = os.getenv('GENIUS_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
MAX_DAILY_REQUESTS = 10000 

# JWT Configuration
SECRET_KEY = os.getenv("SECRET_KEY", "7fd98e0a8b9c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

# Password Hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# Default Admin (In a real app, this should be in the database)
# admin123 hash
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD_HASH = "$2b$12$UH2T7wSJEdcSfrAbSL6Q0uJT8ramsruDrmf1Uf2Fs5iORBG5iPBPq" 

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.datetime.utcnow() + datetime.timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(access_token: Optional[str] = Cookie(None)):
    credentials_exception = HTTPException(
        status_code=401,
        detail="Could not validate credentials",
    )
    if not access_token:
        raise credentials_exception
    try:
        payload = jwt.decode(access_token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    
    if username != ADMIN_USERNAME:
        raise credentials_exception
    return username

# Lazy load Greek NER pipeline only when explicitly requested
ner_pipeline = None

def get_ner_pipeline():
    global ner_pipeline
    if ner_pipeline is None:
        print("[NER] Lazy loading Greek NLP Pipeline...")
        try:
            from gr_nlp_toolkit import Pipeline
            ner_pipeline = Pipeline("ner")
        except ImportError:
            raise RuntimeError("gr-nlp-toolkit (PyTorch) is not installed on this lightweight API deployment instance.")
    return ner_pipeline

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

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Response Models
class LocationResponse(BaseModel):
    id: int
    location: str
    song: str
    lat: Optional[float]
    lng: Optional[float]
    is_manual: bool

    class Config:
        from_attributes = True

class LocationUpdateRequest(BaseModel):
    lat: float
    lng: float

class ArtistLocationsResponse(BaseModel):
    artist: str
    mentions: List[LocationResponse]

class LoginResponse(BaseModel):
    message: str

class ReportCreateRequest(BaseModel):
    location_id: int
    report_type: str
    suggestion: Optional[str] = None

class ReportResponse(BaseModel):
    id: int
    location_id: int
    location_name: str
    song: str
    artist: str
    report_type: str
    suggestion: Optional[str]
    created_at: datetime.date

ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://lyricmap.gr,https://lyricmap.gr,http://localhost:4200,http://localhost:3000,http://localhost:5173").split(",")
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in ALLOWED_ORIGINS],
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

def extract_locations_ner(text, chunk_size=200):
    words = text.split()
    chunks = [' '.join(words[i:i + chunk_size]) for i in range(0, len(words), chunk_size)]
    locations = set()
    
    pipeline = get_ner_pipeline()
    for chunk in chunks:
        try:
            doc = pipeline(chunk)
            current_location = []
            
            for token in doc.tokens:
                # gr-nlp-toolkit uses IOBES encoding for NER
                # S: Single, B: Begin, I: Inside, E: End, O: Outside
                # Tags include: LOC (Location), GPE (Geo-Political Entity), FAC (Facility)
                ner_tag = token.ner
                is_location = any(ner_tag.endswith(t) for t in ["-LOC", "-GPE", "-FAC"])
                
                if is_location:
                    if ner_tag.startswith("S-"):
                        locations.add(token.text)
                    elif ner_tag.startswith("B-"):
                        current_location = [token.text]
                    elif ner_tag.startswith("I-"):
                        current_location.append(token.text)
                    elif ner_tag.startswith("E-"):
                        current_location.append(token.text)
                        locations.add(" ".join(current_location))
                        current_location = []
                else:
                    current_location = []
        except Exception as e:
            print(f"  [NER ERROR] Failed to process chunk: {e}")
            continue
                
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
                try:
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
                                        lng=coords.get("lng"),
                                        is_manual=False
                                    )
                                    db.add(new_mention)
                                    db.commit()
                                elif not existing_mention.is_manual:
                                    # Update existing mention if not manual
                                    existing_mention.lat = coords.get("lat")
                                    existing_mention.lng = coords.get("lng")
                                    db.commit()

                                # (15 RPM = 1 call every 4 seconds)
                                time.sleep(4)
                            except Exception as loc_e:
                                print(f"  [ERROR] Failed to process location '{loc}': {loc_e}")
                                db.rollback()
                                continue
                        
                        song_obj.is_processed = True
                        db.commit()
                except Exception as song_e:
                    print(f"  [ERROR] Fatal error processing song '{song.title}': {song_e}")
                    db.rollback()
                    continue
            
            print(f"--- Finished updating {artist_name} ---")
        else:
            print(f"--- Artist {artist_name} not found ---")
            
    except Exception as e:
        print(f"--- Error processing {artist_name}: {e} ---")
        db.rollback()
    finally:
        db.close()

@app.get("/")
def read_root():
    return {"message": "LyricMap API is running", "endpoints": ["/locations", "/docs", "/process-all"]}

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
                    id=mention.id,
                    location=mention.location_name,
                    song=song.title,
                    lat=mention.lat,
                    lng=mention.lng,
                    is_manual=mention.is_manual
                ))
        
        if mentions:
            response.append(ArtistLocationsResponse(
                artist=artist.name,
                mentions=mentions
            ))
            
    return response

@app.post("/process-all")
def trigger_all_processing(background_tasks: BackgroundTasks, current_user: Annotated[str, Depends(get_current_user)]):
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
def trigger_artist_processing(artist_name: str, background_tasks: BackgroundTasks, current_user: Annotated[str, Depends(get_current_user)]):
    """Trigger processing for a specific artist."""
    background_tasks.add_task(process_artist_task, artist_name)
    return {"message": f"Processing started in background for {artist_name}."}

@app.post("/token", response_model=LoginResponse)
async def login(response: Response, form_data: Annotated[OAuth2PasswordRequestForm, Depends()]):
    if form_data.username != ADMIN_USERNAME or not verify_password(form_data.password, ADMIN_PASSWORD_HASH):
        raise HTTPException(status_code=400, detail="Incorrect username or password")
    
    access_token = create_access_token(data={"sub": form_data.username})
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        samesite="lax",
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        secure=COOKIE_SECURE
    )
    return {"message": "Login successful"}

@app.post("/auth/logout")
async def logout(response: Response):
    response.delete_cookie(key="access_token", samesite="lax")
    return {"message": "Logged out successfully"}

@app.get("/auth/me")
async def get_me(current_user: Annotated[str, Depends(get_current_user)]):
    return {"username": current_user}

@app.put("/locations/{mention_id}")
def update_location(
    mention_id: int, 
    request: LocationUpdateRequest, 
    db: Annotated[Session, Depends(get_db)], 
    current_user: Annotated[str, Depends(get_current_user)]
):
    """Update a specific location mention's coordinates and mark as manual."""
    mention = db.query(LocationMention).filter(LocationMention.id == mention_id).first()
    if not mention:
        raise HTTPException(status_code=404, detail="Location mention not found")
    
    mention.lat = request.lat
    mention.lng = request.lng
    mention.is_manual = True
    db.commit()
    return {"message": "Location updated successfully", "id": mention_id, "is_manual": True}

@app.post("/reports")
@limiter.limit("5/day")
def create_report(request: Request, report_req: ReportCreateRequest, db: Session = Depends(get_db)):
    mention = db.query(LocationMention).filter(LocationMention.id == report_req.location_id).first()
    if not mention:
        raise HTTPException(status_code=404, detail="Location mention not found")
        
    new_report = Report(
        location_id=report_req.location_id,
        report_type=report_req.report_type,
        suggestion=report_req.suggestion
    )
    db.add(new_report)
    db.commit()
    db.refresh(new_report)
    return {"message": "Report submitted successfully", "id": new_report.id}

@app.get("/reports", response_model=List[ReportResponse])
def get_reports(db: Session = Depends(get_db), current_user: str = Depends(get_current_user)):
    reports = db.query(Report).all()
    res = []
    for r in reports:
        loc = r.location
        if loc and loc.song and loc.song.artist:
            res.append({
                "id": r.id,
                "location_id": r.location_id,
                "location_name": loc.location_name,
                "song": loc.song.title,
                "artist": loc.song.artist.name,
                "report_type": r.report_type,
                "suggestion": r.suggestion,
                "created_at": r.created_at
            })
    return res

@app.delete("/reports/{report_id}")
def resolve_report(report_id: int, db: Session = Depends(get_db), current_user: str = Depends(get_current_user)):
    report = db.query(Report).filter(Report.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    
    db.delete(report)
    db.commit()
    return {"message": "Report resolved"}

if __name__ == "__main__":
    import uvicorn
    # Start the server
    uvicorn.run(app, host="0.0.0.0", port=8000)


