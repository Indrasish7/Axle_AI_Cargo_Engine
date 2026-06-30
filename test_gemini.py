import os
from google import genai
from google.genai import types

# Load env variables from .env
if os.path.exists(".env"):
    with open(".env", "r") as f:
        for line in f:
            if "=" in line:
                key, val = line.strip().split("=", 1)
                os.environ[key.strip()] = val.strip()

client = genai.Client()
print("Client init args / parameters:")
import inspect
print(inspect.signature(genai.Client.__init__))
print("\ngenerate_content signature:")
print(inspect.signature(client.models.generate_content))

print("\nChecking types in google.genai.types:")
try:
    print("HttpOptions attributes:", [attr for attr in dir(types) if "http" in attr.lower() or "option" in attr.lower()])
    print("HttpOptions class:", inspect.signature(types.HttpOptions.__init__))
except Exception as e:
    print("Error inspecting HttpOptions:", e)
