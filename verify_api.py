from fastapi.testclient import TestClient
import json
from importlib import import_module

# Dynamically import the app from rest-api.py 
# (using importlib because of the hyphen in the filename)
rest_api = import_module("rest-api")
app = rest_api.app

client = TestClient(app)

def test_get_locations():
    response = client.get("/locations")
    assert response.status_code == 200
    data = response.json()
    
    # Check structure
    assert isinstance(data, list)
    if len(data) > 0:
        first_artist = data[0]
        assert "artist" in first_artist
        assert "mentions" in first_artist
        assert isinstance(first_artist["mentions"], list)
        
        if len(first_artist["mentions"]) > 0:
            first_mention = first_artist["mentions"][0]
            assert "location" in first_mention
            assert "song" in first_mention
            assert "lat" in first_mention
            assert "lng" in first_mention

    print("Verification Successful: API response format is correct.")
    print(f"Sample data from first artist: {json.dumps(data[0], indent=2, ensure_ascii=False) if data else 'No data'}")

if __name__ == "__main__":
    try:
        test_get_locations()
    except Exception as e:
        print(f"Verification Failed: {e}")
        import traceback
        traceback.print_exc()
