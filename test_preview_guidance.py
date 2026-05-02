#!/usr/bin/env python3
"""
Test that the extraction endpoint now includes preview_data in the response.
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
print("TEST: Extraction endpoint includes preview guidance")
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
    
    print("✅ Request successful")
    print(f"\nResponse includes:")
    
    # Check for preview guidance
    checks = [
        ("next_actions.preview_endpoint", "preview_endpoint" in data.get("next_actions", {})),
        ("preview_endpoint points to /api/mcp/preview", 
         data.get("next_actions", {}).get("preview_endpoint") == "/api/mcp/preview"),
        ("preview_data included", "preview_data" in data),
        ("preview_data.article_title", "article_title" in data.get("preview_data", {})),
        ("preview_data.phrases", "phrases" in data.get("preview_data", {})),
        ("preview_data.shortlisted", "shortlisted" in data.get("preview_data", {})),
    ]
    
    all_passed = True
    for check_name, result in checks:
        status = "✅" if result else "❌"
        print(f"  {status} {check_name}")
        if not result:
            all_passed = False
    
    if all_passed:
        print("\n✨ Perfect! Claude.ai can now use this response to:")
        print("  1. See the preview_endpoint in next_actions")
        print("  2. Extract all the data needed (phrases, shortlisted, article_title)")
        print("  3. Call /api/mcp/preview with the preview_data to render the gallery")
        print("\n🎯 This enables the complete Claude workflow:")
        print("   Article → /api/mcp/claude-article-auto → /api/mcp/preview → Gallery UI")
    else:
        print("\n❌ Some checks failed - response structure may be incomplete")
        
except Exception as e:
    print(f"❌ Error: {e}")
    exit(1)

print("\n" + "=" * 80)
