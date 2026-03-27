#!/usr/bin/env python3
"""Start the Agent Worker Manager."""

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "manager.app:app",
        host="0.0.0.0",
        port=9090,
        reload=True,
    )
