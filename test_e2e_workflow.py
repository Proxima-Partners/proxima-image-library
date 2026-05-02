#!/usr/bin/env python3
"""
End-to-end test of the complete workflow:
1. Call /api/mcp/claude-article-auto to extract phrases and search for images
2. Call /api/mcp/preview with the results to generate the interactive gallery
3. Verify both endpoints work together
"""
import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()

MCP_SECRET = os.getenv("MCP_INTERNAL_SECRET")
BASE_URL = os.getenv("NGROK_URL", "http://localhost:5000")

if not MCP_SECRET:
    print("ERROR: MCP_INTERNAL_SECRET not found in .env")
    exit(1)

print("=" * 80)
print("END-TO-END WORKFLOW TEST: Extraction → Preview Gallery")
print("=" * 80)

# Test article
article = {
    "title": "The Future of AI-Powered Photography",
    "body": """
    Artificial intelligence is revolutionizing the world of photography, from automated 
    subject detection to intelligent filtering and enhancement. Machine learning models 
    are now capable of recognizing scenes, adjusting exposure, and even suggesting 
    composition improvements in real-time. Professional photographers are using neural 
    networks to accelerate their workflows, while hobbyists benefit from computational 
    photography features built into their smartphones.
    
    The integration of AI into camera hardware has led to unprecedented capabilities. 
    Cameras can now identify faces, objects, and scenes with remarkable accuracy. 
    Robotic systems are being deployed for automated surveillance and time-lapse 
    photography. The convergence of artificial intelligence and photography continues 
    to create new possibilities for creative expression and technical innovation.
    """
}

# STEP 1: Extract phrases and search for images
print("\n[STEP 1] Calling /api/mcp/claude-article-auto (extraction + search)")
print(f"Article: {article['title']}")

extraction_payload = {
    "article_title": article["title"],
    "article_body": article["body"],
    "photo_suggestions": [],
    "approval_mode": "manual",
    "search_limit": 5,
}

try:
    extraction_response = requests.post(
        f"{BASE_URL}/api/mcp/claude-article-auto",
        json=extraction_payload,
        headers={"X-MCP-Secret": MCP_SECRET},
        timeout=30
    )
    
    if extraction_response.status_code != 200:
        print(f"❌ Extraction failed: {extraction_response.status_code}")
        print(extraction_response.text[:500])
        exit(1)
    
    extraction_data = extraction_response.json()
    print(f"✅ Extraction successful")
    print(f"   - Phrases extracted: {extraction_data.get('phrase_count', 0)}")
    print(f"   - Images found: {extraction_data.get('shortlisted_count', 0)}")
    
    phrases = extraction_data.get("phrases", [])
    shortlisted = extraction_data.get("shortlisted", [])
    
    if not phrases:
        print("⚠️ No phrases extracted, skipping preview test")
        exit(0)
    
    if not shortlisted:
        print("⚠️ No images found, skipping preview test")
        exit(0)
    
    print(f"\n   Extracted phrases:")
    for p in phrases[:5]:
        print(f"     • {p}")
    
    print(f"\n   Found images:")
    for img in shortlisted[:3]:
        print(f"     • {img.get('title', 'Untitled')} ({img.get('library')})")

except Exception as e:
    print(f"❌ Extraction request failed: {e}")
    exit(1)

# STEP 2: Preview with interactive gallery
print("\n[STEP 2] Calling /api/mcp/preview (generate gallery)")

preview_payload = {
    "article_title": article["title"],
    "phrases": phrases,
    "shortlisted": shortlisted,
}

try:
    preview_response = requests.post(
        f"{BASE_URL}/api/mcp/preview",
        json=preview_payload,
        headers={"X-MCP-Secret": MCP_SECRET},
        timeout=10
    )
    
    if preview_response.status_code != 200:
        print(f"❌ Preview failed: {preview_response.status_code}")
        print(preview_response.text[:500])
        exit(1)
    
    # Check response is HTML
    if "<!DOCTYPE html" not in preview_response.text[:100]:
        print(f"❌ Preview returned non-HTML content")
        exit(1)
    
    print(f"✅ Preview endpoint returned valid HTML")
    
    # Verify key UI elements
    checks = [
        ("Image gallery grid", "gallery" in preview_response.text),
        ("Selection checkboxes", "image-checkbox" in preview_response.text),
        ("Select All control", "select-all" in preview_response.text),
        ("Catalog button", "Catalog Selected" in preview_response.text),
        ("Article title display", article["title"] in preview_response.text),
        ("Image count matches", f'data-index="{len(shortlisted)-1}"' in preview_response.text),
    ]
    
    print("\n   UI Elements:")
    all_passed = True
    for check_name, result in checks:
        status = "✅" if result else "❌"
        print(f"     {status} {check_name}")
        if not result:
            all_passed = False
    
    if all_passed:
        print("\n✅ All checks passed!")
        print("\nWorkflow Summary:")
        print(f"  1. Extracted {extraction_data['phrase_count']} phrases from article")
        print(f"  2. Found {len(shortlisted)} images across stock photo libraries")
        print(f"  3. Generated interactive preview gallery")
        print(f"  4. User can now select images and catalog them with AI alt text")
    else:
        print("\n⚠️ Some checks failed")
        
except Exception as e:
    print(f"❌ Preview request failed: {e}")
    exit(1)

print("\n" + "=" * 80)
print("✨ END-TO-END WORKFLOW TEST COMPLETE")
print("=" * 80)
