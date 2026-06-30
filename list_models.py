import os
import sys
from openai import OpenAI

NVIDIA_API_KEY   = "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"
NVIDIA_BASE_URL  = "https://integrate.api.nvidia.com/v1"

def list_models():
    client = OpenAI(base_url=NVIDIA_BASE_URL, api_key=NVIDIA_API_KEY)
    try:
        models = client.models.list()
        print("Available models:")
        for m in models:
            print(f"  - {m.id}")
    except Exception as e:
        print(f"Error listing models: {e}")

if __name__ == "__main__":
    list_models()
