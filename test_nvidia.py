import os
import sys
from openai import OpenAI

NVIDIA_API_KEY   = "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"
NVIDIA_BASE_URL  = "https://integrate.api.nvidia.com/v1"
NVIDIA_MODEL     = "meta/llama-3.3-70b-instruct"

def test_key():
    print("Initializing OpenAI client with NVIDIA base URL...")
    client = OpenAI(base_url=NVIDIA_BASE_URL, api_key=NVIDIA_API_KEY)
    
    print(f"Sending a test request using model: {NVIDIA_MODEL}...")
    try:
        completion = client.chat.completions.create(
            model=NVIDIA_MODEL,
            messages=[
                {"role": "user", "content": "Say hello!"}
            ],
            max_tokens=50,
            temperature=0.5,
            timeout=15.0
        )
        print("\n=== RESPONSE SUCCESS ===")
        print(completion.choices[0].message.content.strip())
        print("========================")
        print("The NVIDIA API key is WORKING correctly!")
    except Exception as e:
        print("\n=== RESPONSE ERROR ===")
        print(f"Error occurred: {e}")
        print("======================")
        print("The NVIDIA API key is NOT working or expired.")

if __name__ == "__main__":
    test_key()
