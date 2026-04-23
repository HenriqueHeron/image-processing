import asyncio
import httpx
import time
from collections import Counter

PROXY_URL = "http://localhost:8080/process"

async def send_request(client, req_id):
    try:
        # Each request takes 3 seconds to process
        resp = await client.get(PROXY_URL, params={"seconds": 3}, timeout=10.0)
        data = resp.json()
        print(f"Request {req_id}: Served by {data['container']}")
        return data['container']
    except Exception as e:
        print(f"Request {req_id}: Failed - {e}")
        return None

async def run_test():
    async with httpx.AsyncClient() as client:
        print("--- Phase 1: Sending 10 concurrent requests (Threshold is 5) ---")
        tasks = [send_request(client, i) for i in range(10)]
        results = await asyncio.gather(*tasks)
        
        containers = Counter([r for r in results if r])
        print(f"\nPhase 1 Results: {dict(containers)}")
        
        print("\nWaiting 10 seconds for Docker to spin up new containers...")
        await asyncio.sleep(10)
        
        print("\n--- Phase 2: Sending 10 more concurrent requests ---")
        tasks = [send_request(client, i+10) for i in range(10)]
        results = await asyncio.gather(*tasks)
        
        containers = Counter([r for r in results if r])
        print(f"\nPhase 2 Results: {dict(containers)}")
        
        if len(containers) > 1:
            print("\nSUCCESS: Load balancer distributed requests across multiple containers!")
        else:
            print("\nFAILURE: All requests were served by the same container.")

if __name__ == "__main__":
    asyncio.run(run_test())
