import asyncio
import logging
from collections import defaultdict
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
import httpx
import docker
import os

import threading
import subprocess

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

THRESHOLD = int(os.environ.get("SCALE_THRESHOLD", 5)) 
MAX_CONTAINERS = int(os.environ.get("MAX_CONTAINERS", 10))
COMPOSE_PROJECT = os.environ.get("COMPOSE_PROJECT", "docker")
TARGET_SERVICE = os.environ.get("TARGET_SERVICE", "app")
TARGET_PORT = int(os.environ.get("TARGET_PORT", 8000))

active_connections = defaultdict(int) 
client = docker.from_env()

http_client = httpx.AsyncClient(timeout=30.0)

is_scaling = False
scaling_lock = threading.Lock()

def get_backends():
    backends = []
    try:
        containers = client.containers.list(filters={
            "label": [
                f"com.docker.compose.project={COMPOSE_PROJECT}",
                f"com.docker.compose.service={TARGET_SERVICE}"
            ],
            "status": "running"
        })
        for c in containers:
            networks = c.attrs['NetworkSettings']['Networks']
            if networks:
                ip = list(networks.values())[0]['IPAddress']
                if ip:
                    backends.append(ip)
    except Exception as e:
        logger.error(f"Error discovering backends: {e}")
    return backends

def trigger_scale_up():
    global is_scaling
    with scaling_lock:
        if is_scaling:
            return
        is_scaling = True

    try:
        backends = get_backends()
        if len(backends) >= MAX_CONTAINERS:
            logger.info("Max containers reached.")
            return

        target_count = len(backends) + 1
        logger.info(f"High load detected. Scaling {TARGET_SERVICE} to {target_count} instances...")
        
        # Use subprocess to capture output and errors
        # Running with --no-deps and --no-build to keep it light
        cmd = [
            "docker", "compose", 
            "-p", COMPOSE_PROJECT,
            "-f", "/app/docker-compose.yml", 
            "up", "-d", 
            "--scale", f"{TARGET_SERVICE}={target_count}",
            "--no-recreate",
            "--no-build"
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            logger.info(f"Scale up complete. Output: {result.stdout}")
        else:
            logger.error(f"Scale up failed (exit {result.returncode}). Error: {result.stderr}")
            
    except Exception as e:
        logger.error(f"Error scaling up: {e}")
    finally:
        with scaling_lock:
            is_scaling = False

@app.middleware("http")
async def reverse_proxy(request: Request, call_next):
    # Determine least connections backend
    backends = get_backends()
    if not backends:
        return JSONResponse({"status": "error", "message": "No backends available"}, status_code=502)
    
    # Calculate total active across discovered backends
    total_active = sum(active_connections[ip] for ip in backends)
    
    # Trigger auto-scale if average per container exceeds threshold
    avg_active = total_active / len(backends)
    if avg_active > THRESHOLD:
        # Schedule scale up in background
        asyncio.create_task(asyncio.to_thread(trigger_scale_up))

    # Pick the backend with least connections
    selected_ip = min(backends, key=lambda ip: active_connections[ip])
    
    # Track connection
    active_connections[selected_ip] += 1
    
    # Build URL correctly
    query = f"?{request.url.query}" if request.url.query else ""
    target_url = f"http://{selected_ip}:{TARGET_PORT}{request.url.path}{query}"
    
    logger.info(f"Routing to {selected_ip}. Active: {active_connections[selected_ip]}")
    
    try:
        # Forward the request
        headers = dict(request.headers)
        headers.pop("host", None) # Remove original host to let httpx set it
        
        # Simple proxying
        body = await request.body()
        logger.info(f"Forwarding {request.method} to {target_url} with {len(body)} bytes body")
        try:
            proxy_resp = await http_client.request(
                request.method,
                target_url,
                headers=headers,
                content=body,
                follow_redirects=False
            )
            logger.info(f"Received {proxy_resp.status_code} from {selected_ip}")
            
            # Filter headers
            excluded_headers = {
                "content-encoding", "content-length", "transfer-encoding", 
                "connection", "keep-alive", "date", "server"
            }
            response_headers = {
                k: v for k, v in proxy_resp.headers.items() 
                if k.lower() not in excluded_headers
            }
            
            return Response(
                content=proxy_resp.content,
                status_code=proxy_resp.status_code,
                headers=response_headers
            )
        except Exception as forward_err:
            logger.error(f"Httpx request failed: {forward_err}")
            raise forward_err
    except Exception as e:
        logger.error(f"Proxy error targeting {selected_ip}: {e}")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=502)
    finally:
        active_connections[selected_ip] -= 1
        if active_connections[selected_ip] <= 0:
            active_connections.pop(selected_ip, None)
