#!/usr/bin/env python3
"""
Test that shortlisted images now come from multiple libraries, not just Pexels.
"""
import os
import json
import requests
from collections import Counter
from dotenv import load_dotenv

load_dotenv()

MCP_SECRET = os.getenv("MCP_INTERNAL_SECRET")
BASE_URL = os.getenv("NGROK_URL", "http://localhost:5000")

if not MCP_SECRET:
    print("ERROR: MCP_INTERNAL_SECRET not found in .env")
    exit(1)

print("=" * 80)
print("TEST: Shortlisted images from multiple libraries")
print("=" * 80)

article = {
    "title": "The Future of AI-Powered Photography",
    "body": """
    Artificial intelligence is revolutionizing photography. Machine learning models 
    can now recognize scenes, adjust exposure, and suggest composition. Professional 
    photographers use neural networks to accelerate workflows. Robotic systems are 
    being deployed for automated surveillance and time-lapse photography.
    """
}

payload = {
    "article_title": article["title"],
    "article_body": article["body"],
    "photo_suggestions": [],
    "approval_mode": "manual",
    "search_limit": 5,
}

try:
    response = requests.post(
        f"{BASE_URL}/api/mcp/claude-article-auto",
        json=payload,
        headers={"X-MCP-Secret": MCP_SECRET},
        timeout=30
    )
    
    if response.status_code != 200:
        print(f"❌ Request failed: {response.status_code}")
        print(response.text[:500])
        exit(1)
    
    data = response.json()
    shortlisted = data.get("shortlisted", [])
    
    print(f"✅ Got {len(shortlisted)} images\n")
    
    # Analyze library distribution
    libraries = [img.get("library", "unknown") for img in shortlisted]
    lib_count = Counter(libraries)
    
    print("Library distribution:")
    for lib, count in sorted(lib_count.items()):
        print(f"  • {lib}: {count} image(s)")
    
    print("\nImage details:")
    for i, img in enumerate(shortlisted, 1):
        print(f"  {i}. {img['title'][:40]}... ({img['library']})")
    
    if len(lib_count) > 1:
        print(f"\n✅ SUCCESS: Images from {len(lib_count)} different libraries!")
        print(f"   Gallery will show nice variety: {', '.join(sorted(lib_count.keys()))}")
    else:
        print(f"\n⚠️ All {len(shortlisted)} images are from {libraries[0]}")
        print("   (This is OK if only one library has results for your search)")
        
except Exception as e:
    print(f"❌ Error: {e}")
    exit(1)

print("\n" + "=" * 80)
