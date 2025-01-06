from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import fitz  # PyMuPDF
import firebase_admin
from firebase_admin import credentials, db
import re
import io
import httpx
import json
import os

app = FastAPI()

# Initialize Firebase Admin with service account
if 'FIREBASE_SERVICE_ACCOUNT' in os.environ:
    # Production: Use environment variable
    service_account_info = json.loads(os.environ['FIREBASE_SERVICE_ACCOUNT'])
    cred = credentials.Certificate(service_account_info)
else:
    # Local development: Use file
    cred = credentials.Certificate('magazine-nexus-firebase-adminsdk-6c4rw-761f6d9b91.json')

firebase_admin.initialize_app(cred, {
    'databaseURL': "https://magazine-nexus-default-rtdb.asia-southeast1.firebasedatabase.app"
})

# Add Appwrite configuration
APPWRITE_ENDPOINT = "https://cloud.appwrite.io/v1"
APPWRITE_PROJECT_ID = "676fc20b003ccf154826"
MAGAZINE_BUCKET_ID = "67718396003a69711df7"

async def get_pdf_content(file_id: str) -> bytes:
    """Helper function to fetch PDF content from Appwrite"""
    url = f"{APPWRITE_ENDPOINT}/storage/buckets/{MAGAZINE_BUCKET_ID}/files/{file_id}/download"
    async with httpx.AsyncClient() as client:
        response = await client.get(
            url,
            headers={
                "X-Appwrite-Project": APPWRITE_PROJECT_ID,
            }
        )
        response.raise_for_status()
        return response.content

class SearchResult(BaseModel):
    magazine_id: str
    title: str
    page_number: int
    content_preview: str
    confidence: float

class SearchResponse(BaseModel):
    results: List[SearchResult]
    total_results: int

@app.get("/")
async def root():
    return {"message": "Magazine Nexus API is running"}

@app.get("/api/search/{query}", response_model=SearchResponse)
async def search_magazines(query: str, limit: Optional[int] = 10):
    try:
        # Get magazines from Firebase
        magazines_ref = db.reference('magazines')
        magazines = magazines_ref.get()
        
        results = []
        
        for magazine_id, magazine_data in magazines.items():
            if not magazine_data.get('pdfFileId'):
                continue
                
            try:
                # Get PDF content from Appwrite
                pdf_content = await get_pdf_content(magazine_data['pdfFileId'])
                doc = fitz.open(stream=pdf_content, filetype="pdf")
                
                for page_num in range(len(doc)):
                    page = doc[page_num]
                    text = page.get_text()
                    
                    # Search for query in text
                    matches = re.finditer(query.lower(), text.lower())
                    
                    for match in matches:
                        start = max(0, match.start() - 50)
                        end = min(len(text), match.end() + 50)
                        preview = text[start:end].replace('\n', ' ').strip()
                        
                        # Calculate simple confidence score based on word proximity
                        words = query.lower().split()
                        confidence = 1.0
                        if len(words) > 1:
                            positions = [text.lower().find(word) for word in words]
                            max_dist = max(positions) - min(positions)
                            confidence = 1.0 / (1.0 + max_dist/100.0)
                        
                        results.append(SearchResult(
                            magazine_id=magazine_id,
                            title=magazine_data['title'],
                            page_number=page_num + 1,
                            content_preview=f"...{preview}...",
                            confidence=confidence
                        ))
                
                doc.close()
                
            except Exception as e:
                print(f"Error processing PDF {magazine_id}: {str(e)}")
                continue
        
        # Sort results by confidence
        results.sort(key=lambda x: x.confidence, reverse=True)
        
        # Limit results
        results = results[:limit]
        
        return SearchResponse(
            results=results,
            total_results=len(results)
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
