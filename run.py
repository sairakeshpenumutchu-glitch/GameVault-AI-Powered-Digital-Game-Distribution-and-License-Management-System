"""
GameVault Launcher
Starts the FastAPI application and serves both backend API and frontend UI.
"""

import uvicorn
import os
import sys

if __name__ == "__main__":
    os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend"))
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend"))
    print("==================================================")
    print("  GAMEVAULT SERVER INITIALIZING...")
    print("  Access the Platform at: http://localhost:8000")
    print("==================================================")
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
