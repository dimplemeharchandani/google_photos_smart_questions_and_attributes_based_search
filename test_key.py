import os
from dotenv import load_dotenv
from google import genai

load_dotenv(".env")
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    raise SystemExit("GEMINI_API_KEY is missing from .env")
client = genai.Client(api_key=api_key)

models = [m.name for m in client.models.list()]
print("Key works! Found", len(models), "models, for example:", models[:3])