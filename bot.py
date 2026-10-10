"""Compatibility entry point for local and Render deployments."""
import asyncio
from app.main import main

if __name__ == "__main__":
    asyncio.run(main())
