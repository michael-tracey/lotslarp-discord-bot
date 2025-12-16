import google.generativeai as genai
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configure the API key
gemini_api_key = os.environ.get("LOTSLARP_DISCORD_BOT_GEMINI_API_KEY")
if not gemini_api_key:
    print("Error: LOTSLARP_DISCORD_BOT_GEMINI_API_KEY not found in environment.")
    exit(1)

genai.configure(api_key=gemini_api_key)

print("Available models that support 'generateContent':")
for m in genai.list_models():
    if 'generateContent' in m.supported_generation_methods:
        print(m.name)
