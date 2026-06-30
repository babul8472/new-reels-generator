import requests
import json
import time

NVIDIA_API_KEY   = "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"
NVIDIA_BASE_URL  = "https://integrate.api.nvidia.com/v1"
NVIDIA_MODEL     = "openai/gpt-oss-120b"

def run_test():
    url = f"{NVIDIA_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {NVIDIA_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": NVIDIA_MODEL,
        "messages": [{"role": "user", "content": "Say hello!"}],
        "max_tokens": 50,
        "temperature": 0.5
    }
    
    print(f"Sending raw POST to {url}...")
    start_time = time.time()
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=60)
        duration = time.time() - start_time
        print(f"Request finished in {duration:.2f} seconds.")
        print(f"HTTP Status Code: {response.status_code}")
        print("Response Headers:")
        for k, v in response.headers.items():
            print(f"  {k}: {v}")
        print("\nResponse Body:")
        print(response.text)
    except Exception as e:
        duration = time.time() - start_time
        print(f"Request failed/timed out after {duration:.2f} seconds.")
        print(f"Error: {e}")

if __name__ == "__main__":
    run_test()
