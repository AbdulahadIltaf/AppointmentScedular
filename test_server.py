import sys
import os
from fastapi.testclient import TestClient

# Add workspace to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from main import app

client = TestClient(app)

def test_endpoints():
    print("Starting integration tests...")
    
    # 1. Test Dashboard HTML serving
    print("Testing GET / ...")
    response = client.get("/")
    assert response.status_code == 200
    assert "Apex Dental" in response.text
    print("[OK] GET / returns correct HTML dashboard.")
    
    # 2. Test Get Appointments API
    print("Testing GET /api/appointments/ ...")
    response = client.get("/api/appointments/")
    assert response.status_code == 200
    data = response.json()
    assert len(data) > 0
    assert data[0]["patient_name"] == "John Doe"
    assert data[0]["status"] == "PENDING"
    print("[OK] GET /api/appointments/ returns seeded mock data successfully.")
    
    # 3. Test Get Slots API
    print("Testing GET /api/appointments/slots ...")
    response = client.get("/api/appointments/slots")
    assert response.status_code == 200
    slots = response.json()
    assert len(slots) == 5
    assert "spoken" in slots[0]
    print("[OK] GET /api/appointments/slots returns 5 available scheduling slots.")
    
    # 4. Test TwiML Generation API
    print("Testing GET /api/calls/twiml?appointment_id=1 ...")
    response = client.get("/api/calls/twiml?appointment_id=1")
    assert response.status_code == 200
    assert "application/xml" in response.headers["content-type"]
    assert "<Stream" in response.text
    assert "wss://" in response.text or "ws://" in response.text
    print("[OK] GET /api/calls/twiml generates valid TwiML with WebSocket stream target.")
    
    print("\nAll integration tests passed successfully!")

if __name__ == "__main__":
    try:
        test_endpoints()
    except AssertionError as e:
        print(f"\nAssertion Error during testing: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\nUnexpected error during testing: {e}")
        sys.exit(1)
