import os
import sys
import uvicorn

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass


# Inject Gemini API key into the local environment context
if os.path.exists(".env"):
    with open(".env", "r") as f:
        for line in f:
            if "=" in line:
                key, val = line.strip().split("=", 1)
                os.environ[key.strip()] = val.strip()

if not os.environ.get("GEMINI_API_KEY"):
    raise ValueError("GEMINI_API_KEY not found in environment or .env file.")

from src.api import app

if __name__ == "__main__":
    # Expose the API on all interfaces at port 8000
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)  # Trigger reload
