from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import yt_dlp
import asyncio
import json
import os
from typing import Optional
import httpx
from datetime import datetime
import uuid

app = FastAPI(title="YouTube Downloader API", version="1.0")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class YouTubeDownloader:
    def __init__(self):
        self.ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'force_generic_extractor': False,
        }
    
    def get_video_info(self, url: str):
        """Get video information without downloading"""
        try:
            with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                formats = []
                for f in info.get('formats', []):
                    if f.get('ext'):
                        formats.append({
                            'format_id': f.get('format_id'),
                            'ext': f.get('ext'),
                            'resolution': f.get('resolution', 'N/A'),
                            'filesize': f.get('filesize'),
                            'filesize_fmt': self.format_size(f.get('filesize')),
                            'note': f.get('format_note', 'N/A')
                        })
                
                return {
                    'id': info.get('id'),
                    'title': info.get('title'),
                    'thumbnail': info.get('thumbnail'),
                    'duration': info.get('duration'),
                    'duration_string': info.get('duration_string'),
                    'uploader': info.get('uploader'),
                    'formats': formats,
                    'webpage_url': info.get('webpage_url'),
                    'description': info.get('description'),
                    'view_count': info.get('view_count'),
                    'like_count': info.get('like_count'),
                }
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Error getting video info: {str(e)}")
    
    def format_size(self, size_bytes):
        """Format bytes to human readable size"""
        if not size_bytes:
            return "N/A"
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.2f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.2f} TB"
    
    async def download_video(self, url: str, format_id: str = None):
        """Download video in chunks"""
        ydl_opts = {
            'format': format_id or 'best',
            'quiet': True,
            'no_warnings': True,
            'outtmpl': '-',  # Output to stdout
            'buffer_size': 1024 * 1024,  # 1MB buffer
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                filename = f"{info['title']}.{info['ext']}"
                
                def generate():
                    with ydl.YoutubeDL(ydl_opts) as ydl_instance:
                        for chunk in ydl_instance.stream(url):
                            yield chunk
                
                return StreamingResponse(
                    generate(),
                    media_type='video/mp4' if info.get('ext') == 'mp4' else 'application/octet-stream',
                    headers={
                        'Content-Disposition': f'attachment; filename="{filename}"',
                        'X-Video-Title': info.get('title', 'video'),
                    }
                )
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Download error: {str(e)}")

downloader = YouTubeDownloader()

# WebSocket for real-time updates
class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}
    
    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self.active_connections[client_id] = websocket
    
    def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]
    
    async def send_progress(self, client_id: str, message: dict):
        if client_id in self.active_connections:
            await self.active_connections[client_id].send_json(message)

manager = ConnectionManager()

@app.get("/")
async def root():
    return {"message": "YouTube Downloader API", "status": "active"}

@app.get("/api/info")
async def get_info(url: str):
    """Get video information"""
    info = downloader.get_video_info(url)
    return JSONResponse(content=info)

@app.get("/api/download")
async def download(url: str, format: Optional[str] = None):
    """Download video directly"""
    return await downloader.download_video(url, format)

@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    await manager.connect(websocket, client_id)
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "download":
                # Handle download request via WebSocket
                url = data.get("url")
                format_id = data.get("format")
                
                # Send progress updates
                await manager.send_progress(client_id, {
                    "type": "progress",
                    "message": "Starting download...",
                    "progress": 0
                })
                
                # Simulate progress updates (in real app, track actual progress)
                for i in range(1, 11):
                    await asyncio.sleep(0.5)
                    await manager.send_progress(client_id, {
                        "type": "progress",
                        "message": f"Downloading... {i*10}%",
                        "progress": i*10
                    })
                
                info = downloader.get_video_info(url)
                await manager.send_progress(client_id, {
                    "type": "complete",
                    "message": "Download complete!",
                    "data": {
                        "title": info['title'],
                        "duration": info['duration_string'],
                        "formats": len(info['formats'])
                    }
                })
                
    except WebSocketDisconnect:
        manager.disconnect(client_id)
        print(f"Client {client_id} disconnected")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
