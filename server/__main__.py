"""Run the Gleaner server: python -m server"""

import os

import uvicorn

port = int(os.environ.get("PORT", 8080))
host = "127.0.0.1" if os.environ.get("GLEANER_LOCAL") else "0.0.0.0"
uvicorn.run("server.server:app", host=host, port=port)
