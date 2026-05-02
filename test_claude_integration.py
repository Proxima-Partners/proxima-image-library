#!/usr/bin/env python3
"""
Test Claude integration with Proxima Photo Extractor endpoint.
This demonstrates calling Claude's API and having Claude trigger the webhook.
"""

import os
import json
import requests
from anthropic import Anthropic

# Load environment
from dotenv import load_dotenv
load_dotenv()

CLAUDE_API_KEY = os.getenv('ANTHROPIC_API_KEY')
MCP_SECRET = os.getenv('MCP_INTERNAL_SECRET')
NGROK_URL = "https://nonvenous-vambraced-marion.ngrok-free.dev"
ENDPOINT_URL = f"{NGROK_URL}/api/mcp/claude-article-auto"

def call_proxima_endpoint(article_title: str, article_body: str, approval_mode: str = "manual"):
    """Call the Proxima Photo Extractor endpoint."""
    payload = {
        "article_title": article_title,
        "article_body": article_body,
        "photo_suggestions": [],
        "approval_mode": approval_mode,
        "search_limit": 5,
        "max_catalog_items": 3
    }
    
    headers = {
        "Content-Type": "application/json",
        "X-MCP-Secret": MCP_SECRET
    }
    
    print(f"\n📤 Calling Proxima endpoint: {ENDPOINT_URL}")
    print(f"   Article: {article_title}")
    print(f"   Mode: {approval_mode}")
    
    try:
        response = requests.post(ENDPOINT_URL, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        result = response.json()
        
        print(f"✅ Endpoint response (200 OK)")
        print(f"   Phrases extracted: {result.get('phrase_count', 0)}")
        print(f"   Images shortlisted: {result.get('shortlisted_count', 0)}")
        
        if result.get('shortlisted'):
            print(f"   First image: {result['shortlisted'][0]['title']}")
            print(f"      by {result['shortlisted'][0]['photographer']} ({result['shortlisted'][0]['library']})")
        
        return result
    except requests.exceptions.RequestException as e:
        print(f"❌ Endpoint error: {e}")
        return None

def main():
    print("=" * 70)
    print("Proxima Photo Extractor + Claude Integration Test")
    print("=" * 70)
    print(f"\n🔗 Endpoint: {ENDPOINT_URL}")
    print(f"🔑 Using MCP_INTERNAL_SECRET from .env")
    
    # Test 1: Direct endpoint call (no Claude)
    print("\n" + "=" * 70)
    print("TEST 1: Direct Endpoint Call (No Claude)")
    print("=" * 70)
    
    article_1 = {
        "title": "The Rise of AI in Photography",
        "body": "Artificial intelligence is transforming how we edit photos. Cloud services now offer automatic enhancement, smart cropping, and intelligent filtering. Portrait mode effects that once required expensive software are now standard on smartphones. Machine learning models can reconstruct detail in shadows and highlights, breathing new life into old photographs."
    }
    
    result_1 = call_proxima_endpoint(article_1["title"], article_1["body"], "manual")
    
    # Test 2: Claude integration test
    print("\n" + "=" * 70)
    print("TEST 2: Claude Integration (Claude → Proxima)")
    print("=" * 70)
    
    client = Anthropic()
    conversation_history = []
    
    system_prompt = f"""You are a helpful assistant that can extract photos for articles.
You have access to the Proxima Photo Extractor endpoint at: {ENDPOINT_URL}

When a user provides an article, you can call this endpoint to extract key phrases and search for relevant stock photos.

To call the endpoint, you would make an HTTP POST request with:
- Header: X-MCP-Secret: {MCP_SECRET}
- Body: {{"article_title": "...", "article_body": "...", "photo_suggestions": [], "approval_mode": "manual"}}

The endpoint returns:
- phrase_count: number of key phrases extracted
- phrases: list of extracted phrases
- shortlisted: array of image objects with download_url, photographer, library, title, etc.

Summarize what you find for the user."""

    user_article = """I have an article about urban design and how cities teach lessons.

Here's the content:

"Urban Lessons: When a city becomes your teacher

What happens when the approach that worked somewhere else stops working here? Sometimes the city itself is the teacher — if we're willing to be students.

Cities are complex systems with their own logic. They teach through observation: how people move through spaces, what makes a street vibrant, why some neighborhoods feel alive while others feel empty. 

The best urban designers don't impose solutions. They listen to what the city is already doing, and amplify it."

Can you extract photos for this article using the Proxima Photo Extractor?"""
    
    print(f"\n📝 User message: {user_article[:100]}...")
    
    conversation_history.append({
        "role": "user",
        "content": user_article
    })
    
    response = client.messages.create(
        model="claude-opus-4-1",
        max_tokens=1024,
        system=system_prompt,
        messages=conversation_history
    )
    
    assistant_message = response.content[0].text
    print(f"\n🤖 Claude's response:\n{assistant_message}")
    
    # Now actually call the endpoint with the article
    print("\n" + "-" * 70)
    print("Now calling the actual endpoint with this article...")
    print("-" * 70)
    
    result_2 = call_proxima_endpoint(
        "Urban Lessons: When a city becomes your teacher",
        user_article,
        "manual"
    )
    
    if result_2:
        print("\n📸 Full Results:")
        print(json.dumps({
            "phrases": result_2.get('phrases'),
            "image_count": len(result_2.get('shortlisted', [])),
            "images": [
                {
                    "title": img.get('title'),
                    "photographer": img.get('photographer'),
                    "library": img.get('library'),
                    "url": img.get('download_url')
                }
                for img in result_2.get('shortlisted', [])[:3]
            ]
        }, indent=2))
    
    print("\n" + "=" * 70)
    print("✅ Integration test complete!")
    print("=" * 70)

if __name__ == "__main__":
    main()
