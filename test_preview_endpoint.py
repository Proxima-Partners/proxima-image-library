#!/usr/bin/env python3
"""
Test the /api/mcp/preview endpoint.
"""
import os
import json
import base64
import requests
from dotenv import load_dotenv

load_dotenv()

# Configuration
MCP_SECRET = os.getenv("MCP_INTERNAL_SECRET")
NGROK_URL = os.getenv("NGROK_URL", "http://localhost:5000")
ENDPOINT = f"{NGROK_URL}/api/mcp/preview"

if not MCP_SECRET:
    print("ERROR: MCP_INTERNAL_SECRET not found in .env")
    exit(1)

# Sample payload from a successful article extraction
payload = {
    "article_title": "The Rise of AI in Photography",
    "phrases": [
        "artificial intelligence photography",
        "machine learning image processing",
        "AI-powered camera features",
        "neural networks visual recognition",
        "robotic automation photography"
    ],
    "shortlisted": [
        {
            "phrase": "artificial intelligence photography",
            "library": "pexels",
            "download_url": "https://images.pexels.com/photos/8566886/pexels-photo-8566886.jpeg?cs=srgb&dl=pexels-tara-winstead-8566886.jpg&fm=jpg",
            "title": "Futuristic robotic hand touching digital network",
            "tags": ["robot", "ai", "technology", "digital"],
            "photographer": "Tara Winstead",
            "filename": "futuristic-robotic-hand-touching-digital-network.jpg"
        },
        {
            "phrase": "machine learning image processing",
            "library": "unsplash",
            "download_url": "https://images.unsplash.com/photo-1677442d019ceddc81b28427a5f700b5c8e1b3f4?w=800",
            "title": "Computer code on screen",
            "tags": ["programming", "code", "computer"],
            "photographer": "Kevin Ku",
            "filename": "computer-code-on-screen.jpg"
        },
        {
            "phrase": "AI-powered camera features",
            "library": "pixabay",
            "download_url": "https://pixabay.com/get/g3d7e5c5c7c5c5c5c5c5c5c5c5c5c5c5c5c5c5c5c5c.jpg",
            "title": "Modern camera equipment",
            "tags": ["camera", "photography", "equipment"],
            "photographer": "Unknown",
            "filename": "modern-camera-equipment.jpg"
        }
    ]
}

print("=" * 70)
print("Testing /api/mcp/preview endpoint")
print("=" * 70)
print(f"\nEndpoint: {ENDPOINT}")
print(f"Article: {payload['article_title']}")
print(f"Images: {len(payload['shortlisted'])} to preview")

try:
    response = requests.post(
        ENDPOINT,
        json=payload,
        headers={"X-MCP-Secret": MCP_SECRET},
        timeout=10
    )

    print(f"\nStatus Code: {response.status_code}")

    if response.status_code == 200:
        print("✅ Preview endpoint returned 200 OK")
        
        # Check if response is HTML
        if "<!DOCTYPE html" in response.text[:100]:
            print("✅ Response is valid HTML")
            
            # Save HTML to file for inspection
            with open("test_preview_output.html", "w") as f:
                f.write(response.text)
            print("✅ HTML saved to test_preview_output.html")
            
            # Check for key elements
            checks = [
                ("Image gallery section", "gallery" in response.text),
                ("Select All checkbox", "select-all" in response.text),
                ("Catalog button", "Catalog Selected" in response.text),
                ("Article title in page", payload["article_title"] in response.text),
            ]
            
            print("\nContent Checks:")
            for check_name, result in checks:
                status = "✅" if result else "❌"
                print(f"  {status} {check_name}")
        else:
            print("⚠️ Response is not HTML")
            print(f"First 200 chars: {response.text[:200]}")
    else:
        print(f"❌ Unexpected status code: {response.status_code}")
        print(f"Response: {response.text[:500]}")

except Exception as e:
    print(f"❌ Error: {e}")

print("\n" + "=" * 70)
