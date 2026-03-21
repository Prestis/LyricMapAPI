from google import genai
from google.genai import types
import os
import json
from dotenv import load_dotenv

load_dotenv()

def test_single_request():
    client = genai.Client(api_key=os.getenv('GEMINI_API_KEY'))
    
    # Updated Model ID for March 2026
    MODEL_ID = 'gemini-3.1-flash-lite-preview'
    
    location = "Exarcheia, Athens"
    artist = "Lex"
    
    prompt = f"Provide lat/lng for {location} (context: Greek rapper {artist}). Return ONLY JSON."

    print(f"Testing request for: {location}...")
    
    try:
        response = client.models.generate_content(
            model=MODEL_ID,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type='application/json',
            )
        )
        
        data = json.loads(response.text)
        print("✅ Success!")
        print(json.dumps(data, indent=2))
        
    except Exception as e:
        print(f"❌ Failed: {e}")

if __name__ == "__main__":
    test_single_request()