import socket
import asyncio
import hashlib
from datetime import datetime, timedelta
from typing import Optional
from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
import psycopg2
from psycopg2.extras import RealDictCursor
import redis
import os

app = FastAPI()

# Database configuration
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://admin:admin123@postgres:5432/image_processing")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")

# Database connection
def get_db_connection():
    conn = psycopg2.connect(DATABASE_URL)
    return conn

# Redis connection
redis_client = redis.from_url(REDIS_URL)

# Pydantic models
class UserCreate(BaseModel):
    username: str
    email: str
    password: str

class UserLogin(BaseModel):
    email: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str

class ProcessRequest(BaseModel):
    image_url: str
    processing_type: str

# Database operations
def create_user(username: str, email: str, password: str):
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        
        cursor.execute(
            "INSERT INTO users (username, email, password_hash) VALUES (%s, %s, %s) RETURNING id, username, email, created_at",
            (username, email, password_hash)
        )
        user = cursor.fetchone()
        conn.commit()
        return user
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def authenticate_user(email: str, password: str):
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            "SELECT id, username, email, password_hash FROM users WHERE email = %s",
            (email,)
        )
        user = cursor.fetchone()
        
        if user and hashlib.sha256(password.encode()).hexdigest() == user['password_hash']:
            return user
        return None
    finally:
        conn.close()

def get_user_credits(user_id: int):
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            "SELECT amount FROM credits WHERE user_id = %s",
            (user_id,)
        )
        result = cursor.fetchone()
        return result['amount'] if result else 0
    finally:
        conn.close()

def deduct_credits(user_id: int, amount: int):
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            "UPDATE credits SET amount = amount - %s, updated_at = CURRENT_TIMESTAMP WHERE user_id = %s AND amount >= %s RETURNING amount",
            (amount, user_id, amount)
        )
        result = cursor.fetchone()
        conn.commit()
        return result['amount'] if result else None
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def create_processed_image(user_id: int, original_url: str, processed_url: str, processing_type: str, credits_used: int):
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            "INSERT INTO processed_images (user_id, original_image_url, processed_image_url, processing_type, credits_used) VALUES (%s, %s, %s, %s, %s) RETURNING id, created_at",
            (user_id, original_url, processed_url, processing_type, credits_used)
        )
        result = cursor.fetchone()
        conn.commit()
        return result
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

# Session management
def create_session_token(user_id: int, expires_hours: int = 24):
    token = hashlib.sha256(f"{user_id}_{datetime.now().isoformat()}".encode()).hexdigest()
    expires_at = datetime.now() + timedelta(hours=expires_hours)
    
    # Store in Redis
    redis_client.setex(f"session:{token}", expires_hours * 3600, str(user_id))
    
    # Store in database
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            "INSERT INTO session_tokens (user_id, token_hash, expires_at) VALUES (%s, %s, %s) RETURNING id",
            (user_id, token, expires_at)
        )
        conn.commit()
    finally:
        conn.close()
    
    return token

def validate_session_token(token: str) -> Optional[int]:
    # Check Redis first
    user_id = redis_client.get(f"session:{token}")
    if user_id:
        return int(user_id)
    
    # Check database if not in Redis
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            "SELECT user_id FROM session_tokens WHERE token_hash = %s AND expires_at > CURRENT_TIMESTAMP AND is_active = TRUE",
            (token,)
        )
        result = cursor.fetchone()
        return result['user_id'] if result else None
    finally:
        conn.close()

# API endpoints
@app.get("/")
def root():
    return {"status": "ok", "container": socket.gethostname()}

@app.post("/register")
def register(user: UserCreate):
    try:
        new_user = create_user(user.username, user.email, user.password)
        return {"message": "User created successfully", "user": new_user}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/login")
def login(user: UserLogin):
    authenticated_user = authenticate_user(user.email, user.password)
    if not authenticated_user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    token = create_session_token(authenticated_user['id'])
    return {"access_token": token, "token_type": "bearer"}

@app.get("/health")
def health():
    return {"status": "healthy", "container": socket.gethostname()}

@app.get("/credits")
def get_credits(token: str):
    user_id = validate_session_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    
    credits = get_user_credits(user_id)
    return {"user_id": user_id, "credits": credits}

@app.post("/process")
async def process_image(request: ProcessRequest, token: str):
    user_id = validate_session_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    
    # Check user has enough credits
    credits = get_user_credits(user_id)
    if credits < 1:
        raise HTTPException(status_code=400, detail="Insufficient credits")
    
    # Simulate image processing
    await asyncio.sleep(1)
    
    # Deduct credits
    new_credits = deduct_credits(user_id, 1)
    if new_credits is None:
        raise HTTPException(status_code=400, detail="Failed to deduct credits")
    
    # Create processed image record
    processed_url = f"processed_{hashlib.md5(request.image_url.encode()).hexdigest()}.jpg"
    result = create_processed_image(user_id, request.image_url, processed_url, request.processing_type, 1)
    
    return {
        "status": "processed",
        "container": socket.gethostname(),
        "credits_remaining": new_credits,
        "processed_image_url": processed_url,
        "processed_at": result['created_at']
    }