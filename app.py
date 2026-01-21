"""
Ronit AI Voice Coach - Production-Ready Flask Application

A professional AI voice coaching platform with ElevenLabs integration,
Gemini AI for care plan generation, Mailjet email delivery, and Razorpay payments.
"""

import os
import re
import random
import threading
from threading import Lock
import time
import uuid
import smtplib
import ssl
import json
import base64
import logging
import hmac
import hashlib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple, List, Dict, Any
from functools import wraps

from flask import Flask, jsonify, send_from_directory, abort, request, render_template_string
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv
import requests
from requests.adapters import HTTPAdapter, Retry
from supabase import create_client, Client
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
import jwt
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

import redis


# Load environment variables
load_dotenv()

logging.basicConfig(
    level=logging.INFO if os.getenv("LOG_LEVEL", "INFO").upper() == "INFO" else logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

class Config:
    """Application configuration from environment variables."""
    
    ELEVEN_API_KEY = (os.getenv("ELEVEN_API_KEY") or "").strip()
    AGENT_ID = (os.getenv("AGENT_ID") or os.getenv("ELEVEN_AGENT_ID") or "").strip()
    PORT = int(os.getenv("PORT", "5000"))
    

    FROM_EMAIL = (os.getenv("FROM_EMAIL") or "info@example.com").strip()
    FROM_NAME = (os.getenv("FROM_NAME") or "AI Voice Coach").strip()
    REPLY_TO = (os.getenv("REPLY_TO") or "").strip()
    
    SMTP_HOST = (os.getenv("SMTP_HOST") or "").strip()
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER = (os.getenv("SMTP_USER") or "").strip()
    SMTP_PASSWORD = (os.getenv("SMTP_PASSWORD") or "").strip()
    SMTP_TLS = (os.getenv("SMTP_TLS", "true").lower() == "true")
    
    GEMINI_API_KEY = (os.getenv("GEMINI_API_KEY") or "").strip()
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash").strip()
    
    RAZORPAY_KEY_ID = (os.getenv("RAZORPAY_KEY_ID") or "").strip()
    RAZORPAY_KEY_SECRET = (os.getenv("RAZORPAY_KEY_SECRET") or "").strip()
    RAZORPAY_CURRENCY = (os.getenv("RAZORPAY_CURRENCY") or "INR").strip()
    
    try:
        amount_str = os.getenv("RAZORPAY_AMOUNT_PAISA", "49900").strip()
        amount_str = re.sub(r'[^\d]', '', amount_str)
        RAZORPAY_AMOUNT_PAISA = int(amount_str) if amount_str else 49900
    except (ValueError, AttributeError):
        logger.warning("Invalid RAZORPAY_AMOUNT_PAISA format, using default 49900")
        RAZORPAY_AMOUNT_PAISA = 49900
    
    DEBUG = (os.getenv("DEBUG", "false").lower() == "true")
    ENVIRONMENT = os.getenv("ENVIRONMENT", "production").lower()
    MAX_TRANSCRIPT_LENGTH = int(os.getenv("MAX_TRANSCRIPT_LENGTH", "50000"))
    MAX_EMAIL_LENGTH = int(os.getenv("MAX_EMAIL_LENGTH", "254"))
    
    ADMIN_PASSWORD = (os.getenv("ADMIN_PASSWORD") or "admin123").strip()
    ADMIN_USERNAME = (os.getenv("ADMIN_USERNAME") or "admin").strip()
    
    GOOGLE_CLIENT_ID = (os.getenv("GOOGLE_CLIENT_ID") or "").strip()
    
    JWT_SECRET_KEY = (os.getenv("JWT_SECRET_KEY") or os.getenv("SECRET_KEY")).strip() if (os.getenv("JWT_SECRET_KEY") or os.getenv("SECRET_KEY")) else None
    
    if not JWT_SECRET_KEY:
        if ENVIRONMENT == "production":
            raise ValueError("FATAL: JWT_SECRET_KEY must be set in production!")
        else:
            JWT_SECRET_KEY = os.urandom(32).hex()
            
    JWT_ALGORITHM = "HS256"
    JWT_EXPIRATION_HOURS = 24
    
    SUPABASE_URL = (os.getenv("SUPABASE_URL") or "").strip()
    SUPABASE_KEY = (os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()

ROOT_DIR = Path(__file__).parent
PUBLIC_DIR = ROOT_DIR / "public"
DATA_DIR = ROOT_DIR / "data"
PUBLIC_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)

app = Flask(__name__, static_url_path="", static_folder=str(PUBLIC_DIR))
app.config['SECRET_KEY'] = os.getenv("SECRET_KEY", os.urandom(32).hex())
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload

app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

supabase: Optional[Client] = None
if Config.SUPABASE_URL and Config.SUPABASE_KEY:
    try:
        supabase = create_client(Config.SUPABASE_URL, Config.SUPABASE_KEY)
        logger.info("✅ Supabase client initialized successfully")
    except Exception as e:
        logger.error(f"❌ Failed to initialize Supabase client: {e}")
        raise RuntimeError("Supabase connection is required. Application cannot start without database connection.")

# ===== Redis Configuration =====
# MANDATORY: Redis for Session Persistence
try:
    redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    redis_client.ping()
    logger.info("✅ Redis Connected Successfully")
except Exception as e:
    logger.critical(f"❌ Redis connection failed: {e}. FATAL ERROR: Cannot start without Redis.")
    raise RuntimeError("Redis connection is required for production.")

# ===== Security Headers =====
@app.after_request
def set_security_headers(response):
    """Add security headers to all responses."""
    # CRITICAL: Allow microphone and camera access for all origins (including CDN scripts like 11Labs SDK)
    # Camera is allowed to prevent SDK crashes during device enumeration
    response.headers['Permissions-Policy'] = 'microphone=*, camera=*, geolocation=()'
    
    if Config.ENVIRONMENT == "production":
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return response

# ===== CORS Configuration =====
@app.after_request
def set_cors_headers(response):
    """Set CORS headers if needed."""
    origin = request.headers.get('Origin')
    allowed_origins = os.getenv("ALLOWED_ORIGINS", "").split(",")
    
    if origin and (not allowed_origins or origin in allowed_origins or "*" in allowed_origins):
        response.headers['Access-Control-Allow-Origin'] = origin if origin != "*" else "*"
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, Upgrade, Connection'
        response.headers['Access-Control-Max-Age'] = '3600'
        # WebSocket support headers
        if request.headers.get('Upgrade') == 'websocket':
            response.headers['Connection'] = 'Upgrade'
            response.headers['Upgrade'] = 'websocket'
    
    return response

# ===== Rate Limiting =====
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://",
    headers_enabled=True
)

# ===== HTTP Session with Retries =====
session = requests.Session()
retries = Retry(
    total=3,
    backoff_factor=0.5,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset(["POST", "GET"]),
)
session.mount("https://", HTTPAdapter(max_retries=retries))
session.mount("http://", HTTPAdapter(max_retries=retries))

# ===== Token Cache =====
_TOKEN_CACHE: Tuple[Optional[str], datetime] = (None, datetime.min)
TOKEN_CACHE_TTL = timedelta(seconds=55)

# ==========================================
# GOD LEVEL IN-MEMORY SESSION MANAGER
# ==========================================

SESSION_TTL = 3600  # Session expires after 1 hour of inactivity

# 3. REDIS SESSION MANAGER
# No in-memory fallback allowed.

# [STRICT MODE] Helper to Flush Pending Time
def flush_pending_time(email):
    """Calculates and deducts any time pending in Redis before checking DB."""
    try:
        raw = redis_client.get(f"session:{email}")
        if raw:
            session_data = json.loads(raw)
            # Flush means we are syncing/ending, so we remove the session key
            redis_client.delete(f"session:{email}")
            
            last_hb_str = session_data.get("last_heartbeat", session_data.get("last_seen"))
            last_heartbeat = datetime.fromisoformat(last_hb_str)
            if last_heartbeat.tzinfo is None:
                last_heartbeat = last_heartbeat.replace(tzinfo=timezone.utc)
                
            now = datetime.now(timezone.utc)
            delta_seconds = (now - last_heartbeat).total_seconds()
            
            # Sanity check
            if delta_seconds > 15: delta_seconds = 15
            if delta_seconds < 0: delta_seconds = 0
            
            if delta_seconds > 0:
                # Deduct immediately
                user = get_user(email)
                current = float(user.get("talktime", 0))
                new_bal = max(0, current - delta_seconds)
                update_user(email, {"talktime": new_bal})
    except Exception as e:
        logger.error(f"Failed to flush pending time for {email}: {e}")

def check_and_refill_community_bonus(email: str) -> bool:
    """
    Checks if a Community Member is due for their monthly 15-minute refill.
    Returns True if refilled, False otherwise.
    """
    try:
        response = supabase.table("users").select("*").eq("email", email).execute()
        if not response.data:
            return False
            
        user = response.data[0]
        if not user.get("is_community_member"):
            return False

        last_refill_str = user.get("last_community_refill")
        should_refill = False
        now = datetime.now(timezone.utc)

        if not last_refill_str:
            should_refill = True
        else:
            try:
                if last_refill_str.endswith('Z'):
                    last_refill = datetime.fromisoformat(last_refill_str.replace('Z', '+00:00'))
                else:
                    last_refill = datetime.fromisoformat(last_refill_str)
                
                if last_refill.tzinfo is None:
                    last_refill = last_refill.replace(tzinfo=timezone.utc)
                
                if (now - last_refill).days >= 30:
                    should_refill = True
            except Exception as e:
                logger.error(f"Date parse error for community refill: {e}")
                should_refill = True

        if should_refill:
            try:
                current_talktime = int(user.get("talktime", 0))
                new_talktime = current_talktime + 900
                
                supabase.table("users").update({
                    "talktime": new_talktime,
                    "last_community_refill": now.isoformat()
                }).eq("email", email).execute()
                
                logger.info(f"💎 Community Bonus: Added 15 mins to {email}")
                return True
            except Exception as e:
                logger.error(f"Failed to apply community bonus: {e}")
                
        return False
    except Exception as e:
        logger.error(f"Error in community refill: {e}")
        return False



# [ADD HELPER FUNCTION FOR TRANSACTIONS]
def is_transaction_processed(order_id: str) -> bool:
    """Check if a payment order ID has already been processed."""
    if not supabase: return False
    # Create a 'transactions' table in Supabase if you haven't yet!
    # Schema: id (uuid), order_id (text, unique), email (text), amount (int), created_at (timestamp)
    try:
        res = supabase.table("transactions").select("id").eq("order_id", order_id).execute()
        return len(res.data) > 0
    except Exception:
        return False

def record_transaction(email: str, order_id: str, amount: int):
    """Record a processed transaction."""
    if not supabase: return
    try:
        supabase.table("transactions").insert({
            "order_id": order_id,
            "email": email,
            "amount": amount,
            "created_at": datetime.now(timezone.utc).isoformat()
        }).execute()
    except Exception as e:
        logger.error(f"Failed to record transaction: {e}")


def validate_email(email: str) -> bool:
    """Validate email address format."""
    if not email or len(email) > Config.MAX_EMAIL_LENGTH:
        return False
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))

def sanitize_input(text: str, max_length: int = 50000) -> str:
    """Sanitize user input to prevent injection attacks."""
    if not text:
        return ""
    # Remove null bytes and control characters except newlines and tabs
    text = re.sub(r'[\x00-\x08\x0b-\x0c\x0e-\x1f]', '', text)
    # Limit length
    if len(text) > max_length:
        text = text[:max_length]
    return text.strip()

def validate_blueprint_id(blueprint_id: str) -> bool:
    """Validate blueprint ID format to prevent path traversal."""
    if not blueprint_id:
        return False
    # Only allow alphanumeric, hyphens, underscores, and timestamps
    pattern = r'^[a-zA-Z0-9_-]+$'
    return bool(re.match(pattern, blueprint_id)) and len(blueprint_id) <= 100

class AppError(Exception):
    """Base application error."""
    def __init__(self, message: str, status_code: int = 500, details: Optional[Dict] = None):
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(self.message)

@app.errorhandler(AppError)
def handle_app_error(error: AppError):
    """Handle application errors."""
    logger.error(f"AppError: {error.message}", extra={"details": error.details})
    return jsonify({
        "error": error.__class__.__name__,
        "message": error.message,
        "details": error.details
    }), error.status_code

@app.errorhandler(404)
def handle_not_found(error):
    """Handle 404 errors."""
    return jsonify({"error": "Not Found", "message": "The requested resource was not found"}), 404

@app.errorhandler(500)
def handle_internal_error(error):
    """Handle 500 errors."""
    logger.exception("Internal server error")
    return jsonify({
        "error": "Internal Server Error",
        "message": "An unexpected error occurred"
    }), 500

def _extract_token(payload: dict) -> Optional[str]:
    """Extract token from various response formats."""
    for key in ("token", "access_token", "conversation_token"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    
    for container in ("conversation", "data", "result"):
        obj = payload.get(container)
        if isinstance(obj, dict):
            for key in ("token", "access_token", "conversation_token"):
                value = obj.get(key)
                if isinstance(value, str) and value:
                    return value
    return None

def _candidate_urls() -> List[str]:
    """Get list of candidate URLs for token retrieval."""
    custom_url = os.getenv("ELEVEN_TOKEN_URL")
    urls = [
        custom_url,
        "https://api.elevenlabs.io/v1/convai/conversations",
        "https://api.elevenlabs.io/v1/convai/conversation/token",
        "https://api.elevenlabs.io/v1/convai/conversation",
        "https://api.elevenlabs.io/v1/convai/conversations/create",
    ]
    return [url for url in urls if url]

def _get_eleven_token() -> str:
    """Retrieve conversation token from ElevenLabs API."""
    if not Config.ELEVEN_API_KEY:
        raise AppError("ELEVEN_API_KEY not configured", status_code=500)
    if not Config.AGENT_ID:
        raise AppError("AGENT_ID not configured", status_code=500)

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "xi-api-key": Config.ELEVEN_API_KEY,
        "Connection": "keep-alive",
    }
    body = {"agent_id": Config.AGENT_ID}
    tried = []

    for url in _candidate_urls():
        for method in ("POST", "GET"):
            try:
                resp = session.request(
                    method,
                    url,
                    headers=headers,
                    json=body if method == "POST" else None,
                    params=body if method == "GET" else None,
                    timeout=9
                )
            except requests.RequestException as e:
                tried.append({
                    "url": url,
                    "method": method,
                    "error": f"request_exception:{e.__class__.__name__}"
                })
                continue

            if resp.status_code < 400:
                try:
                    payload = resp.json()
                except Exception:
                    tried.append({
                        "url": url,
                        "method": method,
                        "status": resp.status_code,
                        "error": "non_json",
                        "text": resp.text[:300]
                    })
                    continue
                
                token = _extract_token(payload)
                if token:
                    logger.info(f"Token retrieved successfully via {method} {url}")
                    return token
                
                tried.append({
                    "url": url,
                    "method": method,
                    "status": resp.status_code,
                    "error": "no_token_in_payload",
                    "payload": payload
                })
            else:
                try:
                    snippet = resp.json()
                except Exception:
                    snippet = {"raw": resp.text[:300]}
                tried.append({
                    "url": url,
                    "method": method,
                    "status": resp.status_code,
                    "payload": snippet
                })

    logger.error("All token endpoints failed", extra={"attempts": tried})
    raise AppError("Failed to retrieve token from ElevenLabs", status_code=502, details={"attempts": tried})

def create_token(email: str) -> str:
    """Create a JWT token for the user with 24-hour expiration."""
    payload = {
        "email": email.lower(),
        "exp": datetime.now(timezone.utc) + timedelta(hours=Config.JWT_EXPIRATION_HOURS),
        "iat": datetime.now(timezone.utc)
    }
    token = jwt.encode(payload, Config.JWT_SECRET_KEY, algorithm=Config.JWT_ALGORITHM)
    return token

def token_required(f):
    """Decorator to verify JWT token from Authorization header."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        
        if not auth_header.startswith("Bearer "):
            raise AppError("Missing or invalid authorization header", status_code=401)
        
        token = auth_header.replace("Bearer ", "").strip()
        
        try:
            payload = jwt.decode(token, Config.JWT_SECRET_KEY, algorithms=[Config.JWT_ALGORITHM])
            current_user_email = payload.get("email")
            
            if not current_user_email:
                raise AppError("Invalid token payload", status_code=401)
            
            # Inject current_user_email into the route function
            return f(*args, current_user_email=current_user_email, **kwargs)
            
        except jwt.ExpiredSignatureError:
            raise AppError("Token has expired", status_code=401)
        except jwt.InvalidTokenError as e:
            logger.warning(f"Invalid token: {e}")
            raise AppError("Invalid token", status_code=401)
        except Exception as e:
            logger.exception(f"Token verification error: {e}")
            raise AppError("Token verification failed", status_code=401)
    
    return decorated_function

def load_users() -> Dict[str, Any]:
    """Load all users from Supabase. Raises error if Supabase is not available."""
    if not supabase:
        raise RuntimeError("Supabase connection is required")
    
    try:
        response = supabase.table("users").select("*").execute()
        users_dict = {}
        for user in response.data:
            email_lower = user.get("email", "").lower()
            if email_lower:
                users_dict[email_lower] = user
        return users_dict
    except Exception as e:
        logger.exception(f"Failed to load users from Supabase: {e}")
        raise AppError("Database error: Failed to load users", status_code=500)

def get_user(email: str) -> Optional[Dict[str, Any]]:
    """Get user data by email from Supabase. Raises error if Supabase is not available."""
    email_lower = email.lower()
    
    if not supabase:
        raise RuntimeError("Supabase connection is required")
    
    try:
        response = supabase.table("users").select("*").eq("email", email_lower).execute()
        if response.data:
            return response.data[0]
        return None
    except Exception as e:
        logger.exception(f"Failed to get user from Supabase: {e}")
        raise AppError("Database error: Failed to get user", status_code=500)

def update_user(email: str, data: Dict[str, Any]) -> bool:
    """Update or create user data in Supabase. Raises error if Supabase is not available."""
    email_lower = email.lower()
    
    if not supabase:
        raise RuntimeError("Supabase connection is required")
    
    try:
        # Check if user exists
        existing_user = get_user(email)
        
        user_data = {
            "email": email_lower,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        
        if not existing_user:
            # New user - set defaults
            user_data.update({
                "talktime": 0,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "last_login": None,
                "sessions": [],
                "total_sessions": 0,
                "welcome_bonus_given": False,
                "password_hash": None  # Will be set during signup
            })
        
        # Update with provided data
        user_data.update(data)
        
        supabase.table("users").upsert(user_data, on_conflict="email").execute()
        return True
        
    except Exception as e:
        logger.exception(f"Failed to update user in Supabase: {e}")
        raise AppError("Database error: Failed to update user", status_code=500)

def delete_user(email: str) -> bool:
    """Delete user by email from Supabase. Raises error if Supabase is not available."""
    email_lower = email.lower()
    
    if not supabase:
        raise RuntimeError("Supabase connection is required")
    
    try:
        supabase.table("users").delete().eq("email", email_lower).execute()
        return True
    except Exception as e:
        logger.exception(f"Failed to delete user from Supabase: {e}")
        raise AppError("Database error: Failed to delete user", status_code=500)

def add_talktime_to_user(email: str, amount: int) -> bool:
    """Add talktime to user."""
    user = get_user(email)
    if not user:
        user = {"email": email, "talktime": 0}
    current_talktime = user.get("talktime", 0)
    return update_user(email, {"talktime": max(0, current_talktime + amount)})

def set_user_talktime(email: str, amount: int) -> bool:
    """Set user talktime to specific amount."""
    return update_user(email, {"talktime": max(0, amount)})

def record_user_session(email: str, session_data: Dict[str, Any]) -> bool:
    """Record a user session."""
    user = get_user(email)
    if not user:
        update_user(email, {})
        user = get_user(email)
    
    session_entry = {
        "session_id": session_data.get("session_id", str(uuid.uuid4())[:8]),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "duration": session_data.get("duration", 0),
        "transcript_length": session_data.get("transcript_length", 0)
    }
    
    sessions = user.get("sessions", [])
    if not isinstance(sessions, list):
        sessions = []
    sessions.append(session_entry)
    
    # Keep only last 100 sessions
    if len(sessions) > 100:
        sessions = sessions[-100:]
    
    return update_user(email, {
        "sessions": sessions,
        "total_sessions": len(sessions),
        "last_login": datetime.now(timezone.utc).isoformat()
    })

# ===== Blueprint Storage (Supabase) =====
def save_blueprint_to_disk(blueprint_id: str, data: Dict[str, Any]) -> bool:
    """Save blueprint to Supabase database."""
    if not validate_blueprint_id(blueprint_id):
        logger.error(f"Invalid blueprint_id format: {blueprint_id}")
        return False
    
    if not supabase:
        logger.error("Supabase connection is required for blueprint storage")
        raise RuntimeError("Supabase connection is required")
    
    try:
        # Map data fields to Supabase schema
        blueprint_record = {
            "id": blueprint_id,
            "user_email": data.get("email", ""),
            "session_id": data.get("session_id", ""),
            "content": data.get("content", ""),
            "transcript": data.get("transcript", ""),  # Include transcript if provided
            "created_at": data.get("created", datetime.now(timezone.utc).isoformat())
        }
        
        # Insert or update blueprint in Supabase
        supabase.table("blueprints").upsert(blueprint_record, on_conflict="id").execute()
        logger.info(f"Blueprint saved to Supabase: {blueprint_id}")
        return True
    except Exception as e:
        logger.exception(f"Failed to save blueprint {blueprint_id} to Supabase: {e}")
        raise AppError("Database error: Failed to save blueprint", status_code=500)

def load_blueprint_from_disk(blueprint_id: str) -> Optional[Dict[str, Any]]:
    """Load blueprint from Supabase database."""
    if not validate_blueprint_id(blueprint_id):
        logger.warning(f"Invalid blueprint_id format: {blueprint_id}")
        return None
    
    if not supabase:
        logger.error("Supabase connection is required for blueprint storage")
        raise RuntimeError("Supabase connection is required")
    
    try:
        # Query blueprint from Supabase
        response = supabase.table("blueprints").select("*").eq("id", blueprint_id).execute()
        
        if not response.data or len(response.data) == 0:
            return None
        
        blueprint_record = response.data[0]
        
        # Return in the format expected by view_blueprint route
        return {
            "content": blueprint_record.get("content", ""),
            "email": blueprint_record.get("user_email", ""),
            "session_id": blueprint_record.get("session_id", ""),
            "created": blueprint_record.get("created_at", "")
        }
    except Exception as e:
        logger.exception(f"Failed to load blueprint {blueprint_id} from Supabase: {e}")
        raise AppError("Database error: Failed to load blueprint", status_code=500)

# ==========================================
# GOD LEVEL SMTP EMAIL SYSTEM (HTML Support)
# ==========================================

def _send_email(to_email: str, subject: str, html_body: str) -> bool:
    """
    Send beautiful HTML email using ONLY SMTP.
    Removes dependency on Mailjet or other providers.
    
    Args:
        to_email: Recipient email address
        subject: Email subject
        html_body: Email body (HTML format)
    
    Returns:
        True if email was sent successfully, False otherwise
    """
    # Validate email
    if not validate_email(to_email):
        logger.error(f"Invalid email address: {to_email}")
        return False
    
    # Check Configuration
    if not (Config.SMTP_HOST and Config.SMTP_USER and Config.SMTP_PASSWORD):
        logger.error("❌ SMTP not configured. Cannot send email.")
        return False

    try:
        # Create HTML Message
        msg = MIMEMultipart('alternative')
        msg["Subject"] = subject
        msg["From"] = f"{Config.FROM_NAME} <{Config.FROM_EMAIL}>"
        msg["To"] = to_email
        if Config.REPLY_TO:
            msg["Reply-To"] = Config.REPLY_TO

        # Attach HTML Body
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        # Connect and Send
        context = ssl.create_default_context()
        if Config.SMTP_TLS:
            with smtplib.SMTP(Config.SMTP_HOST, Config.SMTP_PORT) as server:
                server.starttls(context=context)
                server.login(Config.SMTP_USER, Config.SMTP_PASSWORD)
                server.send_message(msg)
        else:
            # SSL Connection (Port 465 usually)
            with smtplib.SMTP_SSL(Config.SMTP_HOST, Config.SMTP_PORT, context=context) as server:
                server.login(Config.SMTP_USER, Config.SMTP_PASSWORD)
                server.send_message(msg)
        
        logger.info(f"✅ HTML Email sent via SMTP to {to_email}")
        return True

    except Exception as e:
        logger.exception(f"❌ SMTP send failed: {e}")
        return False

def _delayed_email_with_link(email: str, link: str, care_plan_content: str, delay_seconds: int):
    """
    Sends an attractive HTML email WITH the Gemini Care Plan summary.
    """
    try:
        if delay_seconds > 0:
            time.sleep(delay_seconds)
            
        subject = "🌟 Your Personal Care Plan from Ronit"
        
        # Convert Markdown to HTML for the email body
        # If you don't want to install 'markdown' lib, just wrap in <pre> tags
        try:
            import markdown
            formatted_content = markdown.markdown(care_plan_content)
        except ImportError:
            # Fallback if markdown lib is missing
            formatted_content = f"<pre style='font-family: sans-serif; white-space: pre-wrap;'>{care_plan_content}</pre>"

        # Professional HTML Template with DYNAMIC CONTENT
        html_body = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: 'Helvetica', 'Arial', sans-serif; background-color: #f4f4f4; margin: 0; padding: 0; }}
                .container {{ max-width: 600px; margin: 20px auto; background: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 10px rgba(0,0,0,0.1); }}
                .header {{ background: #065F46; padding: 30px; text-align: center; color: white; }}
                .header h1 {{ margin: 0; font-size: 24px; font-weight: 700; letter-spacing: 1px; }}
                .content {{ padding: 40px 30px; color: #333333; line-height: 1.6; }}
                .ai-summary {{ background-color: #f0fdf4; border-left: 4px solid #065F46; padding: 15px; margin: 20px 0; border-radius: 4px; }}
                .btn {{ display: block; width: 200px; margin: 30px auto; padding: 15px 0; background: #065F46; color: white; text-align: center; text-decoration: none; border-radius: 50px; font-weight: bold; box-shadow: 0 4px 6px rgba(6, 95, 70, 0.2); }}
                .btn:hover {{ background: #047857; }}
                .footer {{ background: #f9fafb; padding: 20px; text-align: center; font-size: 12px; color: #9ca3af; }}
                h2 {{ color: #065F46; font-size: 20px; margin-top: 0; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>RONIT AI COACH</h1>
                </div>
                <div class="content">
                    <h2>Your Care Plan is Ready</h2>
                    <p>It was great speaking with you today. Based on our conversation, here is your personalized summary:</p>
                    
                    <div class="ai-summary">
                        {formatted_content}
                    </div>

                    <a href="{link}" class="btn">View Full Blueprint</a>
                    
                    <p style="text-align: center; font-size: 14px; color: #666;">(Link is secure and private)</p>
                </div>
                <div class="footer">
                    <p>&copy; 2025 Ronit AI Coach. All rights reserved.</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        ok = _send_email(email, subject, html_body)
        
        if ok:
            logger.info(f"Care plan email (with summary) sent to {email}")
        else:
            logger.error(f"Failed to send care plan email to {email}")
            
    except Exception as e:
        logger.exception(f"Email thread error for {email}: {e}")


# ===== Gemini AI Integration =====
def _call_gemini_mindmap_blueprint(transcript: str) -> str:
    """Generate personalized care plan using Gemini AI in markdown format."""
    if not Config.GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY not configured, returning fallback care plan")
        return f"""# Personalized Care Plan

## Overview
Based on our conversation, here are your personalized recommendations and action steps.

## Key Insights
{transcript[:500]}...

## Next Steps
1. Review the insights from our conversation
2. Implement the recommended actions
3. Track your progress regularly

---
*Note: This is a basic care plan. Configure GEMINI_API_KEY for AI-generated personalized recommendations.*"""
    
    prompt = (
        "You are Ronit, an expert AI coach and care plan specialist. "
        "Analyze the following coaching conversation transcript and create a comprehensive, personalized care plan.\n\n"
        "IMPORTANT: Return the care plan in MARKDOWN format with the following structure:\n\n"
        "# Personalized Care Plan\n\n"
        "## Key Insights\n"
        "[Summarize the main insights and patterns from the conversation]\n\n"
        "## Personalized Recommendations\n"
        "[Provide specific, actionable recommendations based on the conversation]\n\n"
        "## Action Steps\n"
        "[List clear, actionable next steps with priorities]\n\n"
        "## Resources & Strategies\n"
        "[Suggest relevant resources, tools, or strategies tailored to the individual]\n\n"
        "## Follow-up Notes\n"
        "[Any additional notes or reminders]\n\n"
        "Make the care plan:\n"
        "- Professional and well-structured\n"
        "- Actionable with specific steps\n"
        "- Personalized to the individual's needs\n"
        "- Encouraging and supportive\n"
        "- Easy to read and follow\n\n"
        "CONVERSATION TRANSCRIPT:\n"
        f"{transcript}"
    )
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{Config.GEMINI_MODEL}:generateContent?key={Config.GEMINI_API_KEY}"
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    
    try:
        r = session.post(url, json=payload, timeout=30)
        r.raise_for_status()
        data = r.json()
        
        if data.get("candidates") and data["candidates"][0]["content"]["parts"]:
            text = data["candidates"][0]["content"]["parts"][0].get("text", "").strip()
            if text:
                logger.info("Care plan generated successfully via Gemini")
                return text
        
        logger.warning("Gemini returned empty response")
        return f"PERSONALIZED CARE PLAN (Gemini Empty Response):\n{transcript[:200]}..."
    except Exception as e:
        logger.exception(f"Gemini API error: {e}")
        return f"PERSONALIZED CARE PLAN (Gemini API Error):\n{transcript[:200]}..."

# ===== API Routes =====
@app.get("/healthz")
@limiter.exempt  # <--- ADD THIS LINE
def healthz():
    """Health check endpoint for monitoring."""
    return jsonify({
        "ok": True,
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "version": "1.0.0"
    })

@app.get("/")
def index():
    """Serve main index page."""
    return send_from_directory(str(PUBLIC_DIR), "index.html")

@app.get("/manifest.json")
def manifest():
    """Serve manifest.json with correct content type."""
    return send_from_directory(
        str(PUBLIC_DIR),
        "manifest.json",
        mimetype="application/manifest+json"
    )

@app.get("/<path:path>")
def static_files(path):
    """Serve static files from public directory."""
    return send_from_directory(str(PUBLIC_DIR), path)

@app.get("/config")
def get_config():
    """Get public configuration (no sensitive data)."""
    return jsonify({
        "agentId": Config.AGENT_ID or "",
        "hasElevenKey": bool(Config.ELEVEN_API_KEY),
        "hasAgentId": bool(Config.AGENT_ID),
        "agentIdLength": len(Config.AGENT_ID) if Config.AGENT_ID else 0,
        "googleClientId": Config.GOOGLE_CLIENT_ID or "",
        "hasGoogleAuth": bool(Config.GOOGLE_CLIENT_ID),
    })

@app.post("/api/auth/signup")
@limiter.limit("10 per hour")
def signup():
    """User signup endpoint."""
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password", "").strip()
    name = (data.get("name") or "").strip()
    
    # Validation
    if not email or not validate_email(email):
        raise AppError("Valid email address is required", status_code=400)
    
    if not password or len(password) < 6:
        raise AppError("Password must be at least 6 characters long", status_code=400)
    
    # Check if user already exists
    existing_user = get_user(email)
    if existing_user:
        # Check if user has a password (already signed up)
        if existing_user.get("password_hash"):
            raise AppError("An account with this email already exists. Please login instead.", status_code=409)
    
    # Hash password
    password_hash = generate_password_hash(password)
    
    # Create user account
    user_data = {
        "email": email,
        "password_hash": password_hash,
        "talktime": 180,  # 3 minutes free welcome bonus
        "created_at": datetime.now(timezone.utc).isoformat(),
        "last_login": None,
        "sessions": [],
        "total_sessions": 0,
        "welcome_bonus_given": True,
        "welcome_bonus_date": datetime.now(timezone.utc).isoformat()
    }
    
    if name:
        user_data["name"] = name
    
    update_user(email, user_data)
    
    # Generate JWT token for new user
    app_token = create_token(email)
    
    logger.info(f"New user signed up: {email}")
    return jsonify({
        "ok": True,
        "message": "Account created successfully! You can now login.",
        "token": app_token,
        "email": email
    })

@app.post("/api/auth/login")
@limiter.limit("10 per hour")
def login():
    """User login endpoint."""
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password", "").strip()
    
    # Validation
    if not email or not validate_email(email):
        raise AppError("Valid email address is required", status_code=400)
    
    if not password:
        raise AppError("Password is required", status_code=400)
    
    # Get user
    user = get_user(email)
    if not user:
        raise AppError("No account found with this email. Please sign up first.", status_code=404)
    
    # Check if user has a password (signed up)
    password_hash = user.get("password_hash")
    if not password_hash:
        raise AppError("No account found with this email. Please sign up first.", status_code=404)
    
    # Verify password
    if not check_password_hash(password_hash, password):
        raise AppError("Invalid email or password", status_code=401)
    
    # Update last login
    update_user(email, {
        "last_login": datetime.now(timezone.utc).isoformat()
    })
    
    # Generate JWT token
    app_token = create_token(email)
    
    logger.info(f"User logged in: {email}")
    return jsonify({
        "ok": True,
        "message": "Login successful",
        "token": app_token,
        "email": email,
        "name": user.get("name") or email.split("@")[0],
        "talktime": user.get("talktime", 0)
    })

@app.get("/api/user/talktime")
@limiter.limit("50 per hour")
@token_required
def get_user_talktime(current_user_email: str):
    """Get balance with AUTO-REFILL for Community Members."""
    # 1. Flush pending Redis time
    flush_pending_time(current_user_email)
    
    # 2. Check & Apply Monthly Community Refill
    refilled = check_and_refill_community_bonus(current_user_email)
    
    # 3. Return Accurate Balance
    user = get_user(current_user_email)
    if user:
        return jsonify({
            "ok": True,
            "talktime": user.get("talktime", 0),
            "email": current_user_email,
            "is_community_member": user.get("is_community_member", False),
            "is_new": False
        })
    else:
        raise AppError("User not found. Please sign up first.", status_code=404)

@app.post("/api/session/start")
@limiter.limit("20 per minute")
@token_required
def start_secure_session(current_user_email: str):
    """
    The Check-In Desk.
    User asks to speak. We check balance and start the server clock.
    """
    # 2. Check Balance
    user = get_user(current_user_email)

    # [GATEKEEPER] Community Members Only
    if not user.get("is_community_member"):
        logger.warning(f"⛔ Non-community member {current_user_email} tried to access bot")
        return jsonify({"ok": False, "error": "Access Restricted: You must be a Community Member to use Ronit."}), 403

    if not user or int(user.get("talktime", 0)) <= 0:
        return jsonify({"ok": False, "error": "Insufficient Funds"}), 402

    # 3. Create Session
    session_id = str(uuid.uuid4())[:8]
    now_iso = datetime.now(timezone.utc).isoformat()
    
    # 4. Store in Redis (Persistence!)
    session_data = {
        "session_id": session_id,
        "last_heartbeat": now_iso
    }
    
    redis_client.setex(f"session:{current_user_email}", SESSION_TTL, json.dumps(session_data))
    
    logger.info(f"🚀 Session started: {current_user_email} (ID: {session_id})")
    
    # Also log to DB for audit
    update_user(current_user_email, {
        "last_active_heartbeat": now_iso,
        "session_status": "active"
    })
    
    return jsonify({
        "ok": True,
        "session_id": session_id,
        "remaining_seconds": int(user.get("talktime", 0))
    })

@app.post("/api/session/heartbeat")
@limiter.limit("120 per minute")
@token_required
def secure_heartbeat(current_user_email: str):
    lock = redis_client.lock(f"lock:{current_user_email}", timeout=5)
    
    if not lock.acquire(blocking=False):
        user = get_user(current_user_email)
        return jsonify({
            "ok": True,
            "remaining_seconds": float(user.get("talktime", 0)),
            "deducted": 0,
            "note": "locked"
        })
    
    try:
        session_data = None
        raw = redis_client.get(f"session:{current_user_email}")
        if raw: session_data = json.loads(raw)

        if not session_data:
            # Return 400 (not 401!) so frontend doesn't think auth failed
            return jsonify({"ok": False, "action": "restart", "reason": "Session not found in Redis"}), 400

        # RENEW SESSION TTL - Reset timer to 1 hour on every heartbeat
        redis_client.expire(f"session:{current_user_email}", SESSION_TTL)

        last_hb_str = session_data.get("last_heartbeat", session_data.get("last_seen"))
        last_heartbeat = datetime.fromisoformat(last_hb_str)
        
        if last_heartbeat.tzinfo is None:
            last_heartbeat = last_heartbeat.replace(tzinfo=timezone.utc)
        
        now = datetime.now(timezone.utc)
        delta_seconds = (now - last_heartbeat).total_seconds()
        
        MAX_HEARTBEAT_GAP = 10.0
        
        if delta_seconds > MAX_HEARTBEAT_GAP:
            logger.warning(f"Heartbeat timeout ({delta_seconds}s) for {current_user_email}. Terminating.")
            
            deduction = MAX_HEARTBEAT_GAP
            user = get_user(current_user_email)
            current_balance = float(user.get("talktime", 0))
            new_balance = max(0, current_balance - deduction)
            update_user(current_user_email, {"talktime": new_balance})
            
            redis_client.delete(f"session:{current_user_email}")
                
            return jsonify({
                "ok": False, 
                "action": "terminate", 
                "reason": "Connection Unstable / Timeout",
                "remaining_seconds": new_balance
            })

        if delta_seconds < 1.0:
            return jsonify({
                "ok": True,
                "remaining_seconds": float(get_user(current_user_email).get("talktime", 0)),
                "deducted": 0
            })

        if delta_seconds < 0: delta_seconds = 0

        user = get_user(current_user_email)
        current_balance = float(user.get("talktime", 0))
        new_balance = max(0, current_balance - delta_seconds)

        if new_balance <= 0:
            redis_client.delete(f"session:{current_user_email}")

            update_user(current_user_email, {"talktime": 0})
            return jsonify({"ok": False, "action": "terminate", "remaining_seconds": 0})

        update_user(current_user_email, {"talktime": new_balance})
        
        session_data["last_heartbeat"] = now.isoformat()
        if "last_seen" in session_data: del session_data["last_seen"]
        
        redis_client.setex(f"session:{current_user_email}", SESSION_TTL, json.dumps(session_data))

        return jsonify({
            "ok": True,
            "remaining_seconds": new_balance,
            "deducted": delta_seconds
        })
    finally:
        try:
            lock.release()
        except:
            pass

@app.post("/api/session/end")
@token_required
def end_secure_session(current_user_email: str):
    """Ends session and charges for the final seconds."""
    flush_pending_time(current_user_email) # Re-use the helper
    return jsonify({"ok": True})


@app.get("/health")
def health_check():
    """Health check endpoint for Caddy and PM2 monitoring."""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "service": "ronit-ai-coach"
    }), 200

@app.post("/api/user/ping")
@limiter.limit("60 per hour")  # Allow frequent pings
@token_required
def user_ping(current_user_email: str):
    """Update user's last_login to keep them marked as online. Email is extracted from JWT token."""
    # Check if user exists
    user = get_user(current_user_email)
    if not user:
        raise AppError("User not found", status_code=404)
    
    # Update last_login to current time (keeps user marked as online)
    update_user(current_user_email, {
        "last_login": datetime.now(timezone.utc).isoformat()
    })
    
    return jsonify({
        "ok": True,
        "message": "Ping received"
    })

@app.get("/conversation-token")
@limiter.limit("5 per minute")
@token_required
def conversation_token(current_user_email: str):
    """Get conversation token from ElevenLabs (VIP ONLY)."""
    global _TOKEN_CACHE
    
    # --- CHECKS THE ID (VIP Only) ---
    user = get_user(current_user_email)
    if not user or not user.get("is_community_member"):
        logger.warning(f"⛔ Token Denied: {current_user_email} is not a Community Member")
        raise AppError("Access Restricted: VIP Only", status_code=403)
    # -----------------------------------

    # Validate configuration
    if not Config.AGENT_ID or not Config.AGENT_ID.strip():
        raise AppError(
            "Agent ID not configured",
            status_code=400,
            details={"message": "AGENT_ID environment variable is missing or empty"}
        )
    
    if not Config.ELEVEN_API_KEY or not Config.ELEVEN_API_KEY.strip():
        raise AppError(
            "API Key not configured",
            status_code=400,
            details={"message": "ELEVEN_API_KEY environment variable is missing or empty"}
        )
    
    # Check cache
    token, timestamp = _TOKEN_CACHE
    if token and (datetime.now(timezone.utc) - timestamp) < TOKEN_CACHE_TTL:
        logger.debug("Returning cached token")
        return jsonify({"token": token})
    
    # Dev fallback for testing
    if (Config.ELEVEN_API_KEY.lower() in ("dummy", "test")) or (Config.AGENT_ID.lower() in ("dummy", "test")):
        dev_token = "dev_local_token"
        _TOKEN_CACHE = (dev_token, datetime.now(timezone.utc))
        logger.warning("Using dev token (dummy/test keys detected)")
        return jsonify({"token": dev_token})
    
    # Fetch new token
    try:
        token = _get_eleven_token()
        _TOKEN_CACHE = (token, datetime.now(timezone.utc))
        return jsonify({"token": token})
    except AppError:
        raise
    except Exception as e:
        logger.exception("Unexpected error in conversation_token")
        raise AppError("Failed to retrieve conversation token", status_code=500)

# [FIX 1] Clean Async Processing Helper
def process_care_plan_background(app_context, transcript, current_user_email, session_id, blueprint_id, host_url):
    """Background task with application context."""
    # Note: In Flask 2.x+, we can pass the app object and use app.app_context()
    # But since we are inside a request, we might want to capture the context properly.
    # However, 'app' is global here.
    with app.app_context(): 
        try:
            logger.info(f"Starting async care plan for {current_user_email}")
            
            # 1. Generate AI Plan
            care_plan = _call_gemini_mindmap_blueprint(transcript)
            
            # 2. Update Database
            blueprint_data = {
                "content": care_plan,
                "email": current_user_email,
                "created": datetime.now(timezone.utc).isoformat(),
                "session_id": session_id,
                "transcript": transcript
            }
            save_blueprint_to_disk(blueprint_id, blueprint_data)
            
            # 3. Record Session
            try:
                record_user_session(current_user_email, {
                    "session_id": session_id,
                    "duration": len(transcript) // 100,
                    "transcript_length": len(transcript)
                })
            except Exception as e:
                logger.warning(f"Failed to record session in bg: {e}")
            
            # 4. Send Email
            care_plan_link = f"{host_url.rstrip('/')}/blueprint/{blueprint_id}"
            _delayed_email_with_link(current_user_email, care_plan_link, 0)
            
            logger.info(f"Background processing success: {blueprint_id}")
            
        except Exception as e:
            logger.error(f"Background processing failed: {e}")

@app.post("/upload-session")
@limiter.limit("10 per hour")
@token_required
def upload_session(current_user_email: str):
    """Upload session transcript and generate care plan. Email is extracted from JWT token."""
    transcript = (request.form.get("transcript") or "").strip()
    
    # Validate input
    if not transcript:
        raise AppError("Missing transcript", status_code=400)
    
    # Sanitize and validate transcript
    transcript = sanitize_input(transcript, max_length=Config.MAX_TRANSCRIPT_LENGTH)
    if len(transcript) < 10:
        raise AppError("Transcript too short (minimum 10 characters)", status_code=400)
    
    # Generate session ID and timestamp
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    session_id = str(uuid.uuid4())[:8]
    blueprint_id = f"{timestamp}_{session_id}"
    
    # [TASK QUEUE]
    # Insert task into Supabase for the background worker to pick up.
    # This survives server restarts/crashes.
    try:
        supabase.table("tasks").insert({
            "type": "generate_care_plan",
            "payload": {
                "email": current_user_email,
                "transcript": transcript,
                "session_id": session_id,
                "blueprint_id": blueprint_id,
                "host_url": request.host_url
            },
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat()
        }).execute()
        
        logger.info(f"Task queued: {blueprint_id}")
        
    except Exception as e:
        logger.error(f"Failed to queue task for {current_user_email}: {e}")
        # Consider a fallback or error response?
        # For now, log it.
        
    return jsonify({
        "ok": True,
        "message": "Processing queued",
        "blueprint_id": blueprint_id
    })

@app.get("/blueprint/<blueprint_id>")
def view_blueprint(blueprint_id: str):
    """View care plan blueprint."""
    if not validate_blueprint_id(blueprint_id):
        abort(404, description="Invalid blueprint ID format")
    
    blueprint_data = load_blueprint_from_disk(blueprint_id)
    if not blueprint_data:
        abort(404, description="Blueprint not found")
    
    template = r'''<!DOCTYPE html>
<html>
<head>
  <title>📋 Personalized Care Plan</title>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <meta charset="utf-8"/>
  <style>
    @media print {
      .no-print { display: none !important; }
      body { background: #fff; }
    }
    body { font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial; background: #f5f7fb; margin: 0; padding: 24px; }
    .container { max-width: 1024px; margin: 0 auto; background: #ffffff; border-radius: 16px; padding: 24px; box-shadow: 0 10px 30px rgba(0,0,0,.06); }
    h1 { text-align: center; color: #1f2937; margin-top: 0; }
    .meta { display: flex; gap: 12px; flex-wrap: wrap; justify-content: center; margin-bottom: 16px; color: #374151; }
    .meta .chip { background: #eef2ff; color: #1e3a8a; padding: 6px 10px; border-radius: 999px; font-size: 12px; border: 1px solid #c7d2fe; }
    .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px,1fr)); gap: 16px; }
    .box { border: 2px solid #e5e7eb; border-radius: 12px; padding: 14px; background: #fcfcff; }
    .box h3 { margin: 0 0 8px 0; font-size: 16px; color: #111827; }
    .item { margin: 6px 0; padding: 8px; border: 1px dashed #c7d2fe; border-radius: 8px; background: #ffffff; }
    .print-bar { display:flex; justify-content:center; margin: 10px 0 18px; }
    .print-btn { background:#4F46E5; color:white; border:none; padding:10px 16px; border-radius:12px; cursor:pointer; }
    pre { white-space: pre-wrap; word-wrap: break-word; }
  </style>
</head>
<body>
  <div class="container">
    <h1>📋 Your Personalized Care Plan</h1>
    <div class="print-bar no-print"><button class="print-btn" onclick="window.print()">🖨️ Print</button></div>
    <div class="meta">
      <div class="chip">📧 {{ email }}</div>
      <div class="chip">📅 {{ created }}</div>
      <div class="chip">🆔 {{ session_id }}</div>
    </div>
    <div id="grid" class="grid"></div>
    <noscript>
      <pre>{{ content }}</pre>
    </noscript>
  </div>
  <script>
    const raw = `{{ content }}`;
    function parseBlueprint(text){
      const lines = text.split(/\r?\n/).map(l=>l.trim()).filter(Boolean);
      const sections = [];
      let current = null;
      for (const line of lines){
        const main = line.match(/^[-*]\s*\*\*(.+?)\*\*/);
        if (main){
          current = { title: main[1], items: [] };
          sections.push(current);
        } else if (current && line.startsWith('-')){
          current.items.push(line.replace(/^[-*]\s*/, ''));
        }
      }
      return sections.length ? sections : [{ title: 'Blueprint', items: lines }];
    }
    const grid = document.getElementById('grid');
    const data = parseBlueprint(raw);
    for (const sec of data){
      const el = document.createElement('div');
      el.className = 'box';
      const h = document.createElement('h3');
      h.textContent = sec.title;
      el.appendChild(h);
      for (const it of sec.items){
        const d = document.createElement('div');
        d.className = 'item';
        d.textContent = it.replace(/^\*\*|\*\*$/g,'');
        el.appendChild(d);
      }
      grid.appendChild(el);
    }
  </script>
</body>
</html>'''
    return render_template_string(template, **blueprint_data)

@app.post("/api/payments/razorpay/order")
@limiter.limit("20 per hour")
def create_razorpay_order():
    """Create Razorpay payment order."""
    if not Config.RAZORPAY_KEY_ID or not Config.RAZORPAY_KEY_SECRET:
        raise AppError("Razorpay keys not configured", status_code=500)
    
    try:
        payload = request.get_json(silent=True) or {}
        amount = int(payload.get("amount_paisa") or Config.RAZORPAY_AMOUNT_PAISA)
        currency = (payload.get("currency") or Config.RAZORPAY_CURRENCY).upper()
        receipt = payload.get("receipt") or f"rcpt_{uuid.uuid4().hex[:10]}"
        
        # Validate amount
        if amount <= 0 or amount > 100000000:  # Max 10,000,000 paise (100,000 INR)
            raise AppError("Invalid amount", status_code=400)
        
        r = session.post(
            "https://api.razorpay.com/v1/orders",
            auth=(Config.RAZORPAY_KEY_ID, Config.RAZORPAY_KEY_SECRET),
            json={
                "amount": amount,
                "currency": currency,
                "receipt": receipt,
                "payment_capture": 1,
            },
            timeout=20,
        )
        
        if r.status_code >= 400:
            try:
                err = r.json()
            except Exception:
                err = {"raw": r.text[:300]}
            logger.error(f"Razorpay order failed: {err}")
            raise AppError("Razorpay order creation failed", status_code=502, details=err)
        
        data = r.json()
        logger.info(f"Razorpay order created: {receipt}")
        return jsonify({
            "ok": True,
            "order": data,
            "key_id": Config.RAZORPAY_KEY_ID
        })
    except AppError:
        raise
    except Exception as e:
        logger.exception("Razorpay order exception")
        raise AppError("Payment order creation failed", status_code=500)

@app.post("/api/payments/razorpay/verify")
@limiter.limit("20 per hour")
@token_required
def verify_razorpay_payment(current_user_email: str):
    try:
        data = request.get_json(silent=True) or {}
        razorpay_order_id = data.get("razorpay_order_id")
        razorpay_payment_id = data.get("razorpay_payment_id")
        razorpay_signature = data.get("razorpay_signature")
        
        if not all([razorpay_order_id, razorpay_payment_id, razorpay_signature]):
            raise AppError("Missing payment details", status_code=400)

        # 1. CHECK FOR REPLAY ATTACK
        if is_transaction_processed(razorpay_order_id):
            logger.warning(f"Replay attack attempt by {current_user_email} with order {razorpay_order_id}")
            raise AppError("Transaction already processed", status_code=400)

        # 2. Verify Signature
        msg = f"{razorpay_order_id}|{razorpay_payment_id}"
        generated_signature = hmac.new(
            Config.RAZORPAY_KEY_SECRET.encode('utf-8'),
            msg.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        if not hmac.compare_digest(generated_signature, razorpay_signature):
            raise AppError("Invalid payment signature", status_code=400)

        # 3. Add Talktime & Record Transaction (Atomic-ish)
        # Using 100 credits as per your logic
        if add_talktime_to_user(current_user_email, 100):
            record_transaction(current_user_email, razorpay_order_id, 100)
            
            user = get_user(current_user_email)
            return jsonify({
                "ok": True, 
                "message": "Payment verified", 
                "new_talktime": user.get("talktime")
            })
        else:
            raise AppError("Failed to update balance", status_code=500)
            
    except Exception as e:
        logger.exception("Payment verification failed")
        raise AppError(str(e), status_code=500)

@app.get("/email/test")
@limiter.limit("5 per hour")
def email_test():
    """Test email configuration."""
    to = (request.args.get("to") or "").strip()
    if not to:
        raise AppError("Provide ?to=email@example.com", status_code=400)
    
    if not validate_email(to):
        raise AppError("Invalid email address format", status_code=400)
    
    ok = _send_email(
        to,
        "Test from AI Voice Coach",
        "This is a test email. If you received it, your email setup works."
    )
    return jsonify({"ok": ok})

# ===== Admin Routes =====
@app.get("/admin")
def admin_page():
    """Serve admin page."""
    return send_from_directory(str(PUBLIC_DIR), "admin.html")

@app.post("/api/admin/login")
@limiter.limit("10 per hour")
def admin_login():
    """Admin login endpoint."""
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()
    
    if username == Config.ADMIN_USERNAME and password == Config.ADMIN_PASSWORD:
        # Create admin session token
        session_token = base64.b64encode(f"{username}:{datetime.now(timezone.utc).isoformat()}".encode()).decode()
        return jsonify({
            "ok": True,
            "token": session_token,
            "message": "Login successful"
        })
    else:
        raise AppError("Invalid username or password", status_code=401)

def verify_admin_token():
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise AppError("Missing or invalid authorization header", status_code=401)
    
    token = auth_header.replace("Bearer ", "").strip()
    try:
        decoded = base64.b64decode(token).decode()
        # Expect format: username:iso_timestamp
        username, timestamp_str = decoded.split(":", 1)
        
        if username != Config.ADMIN_USERNAME:
            raise AppError("Invalid username", status_code=401)
            
        # Check Expiration (24 hours)
        token_time = datetime.fromisoformat(timestamp_str)
        if datetime.now(timezone.utc) - token_time > timedelta(hours=24):
             raise AppError("Token expired", status_code=401)
             
        return True
    except Exception:
        pass
    raise AppError("Invalid or expired token", status_code=401)

# ==========================================
# ADMIN: COMMUNITY MEMBER MANAGEMENT
# ==========================================

@app.post("/api/admin/community/add")
@limiter.limit("50 per hour")
def add_community_member():
    """Promote a user to Community Member."""
    verify_admin_token()
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    
    if not validate_email(email):
        raise AppError("Invalid email", status_code=400)
    
    try:
        response = supabase.table("users").select("*").eq("email", email).execute()
        if not response.data:
            raise AppError("User not found", status_code=404)
        
        supabase.table("users").update({
            "is_community_member": True
        }).eq("email", email).execute()
        
        return jsonify({"ok": True, "message": f"{email} is now a Community Member!"})
    except AppError:
        raise
    except Exception as e:
        logger.error(f"Error adding community member: {e}")
        raise AppError("Database error", status_code=500)

@app.post("/api/admin/community/remove")
@limiter.limit("50 per hour")
def remove_community_member():
    """Remove community member status."""
    verify_admin_token()
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    
    try:
        supabase.table("users").update({
            "is_community_member": False,
            "last_community_refill": None
        }).eq("email", email).execute()
        
        return jsonify({"ok": True, "message": f"{email} removed from Community."})
    except Exception as e:
        logger.error(f"Error removing community member: {e}")
        raise AppError("Database error", status_code=500)

@app.get("/api/admin/users")
@limiter.limit("100 per hour")
def get_all_users():
    """Get all users (admin only)."""
    verify_admin_token()
    users = load_users()
    
    # Format user data for display
    users_list = []
    now = datetime.now(timezone.utc)
    
    for email, user_data in users.items():
        last_login_str = user_data.get("last_login")
        last_login_dt = None
        is_online = False
        
        if last_login_str:
            try:
                # Parse ISO format datetime
                if isinstance(last_login_str, str):
                    # Handle both with and without timezone
                    if last_login_str.endswith('Z'):
                        last_login_dt = datetime.fromisoformat(last_login_str.replace('Z', '+00:00'))
                    elif '+' in last_login_str or last_login_str.count('-') >= 3:
                        # Has timezone info
                        last_login_dt = datetime.fromisoformat(last_login_str)
                    else:
                        # No timezone, assume UTC
                        last_login_dt = datetime.fromisoformat(last_login_str.replace('Z', '') + '+00:00')
                else:
                    last_login_dt = last_login_str
                
                # Consider user online if last login was within last 15 minutes
                if last_login_dt:
                    # Ensure timezone aware
                    if last_login_dt.tzinfo is None:
                        last_login_dt = last_login_dt.replace(tzinfo=timezone.utc)
                    time_diff = (now - last_login_dt).total_seconds()
                    is_online = time_diff < 900  # 15 minutes
            except Exception as e:
                logger.warning(f"Failed to parse last_login for {email}: {e}")
        
        sessions = user_data.get("sessions", [])
        if not isinstance(sessions, list):
            sessions = []
        
        # Calculate total session duration
        total_duration = sum(s.get("duration", 0) for s in sessions)
        
        users_list.append({
            "email": user_data.get("email", email),
            "talktime": user_data.get("talktime", 0),
            "is_community_member": user_data.get("is_community_member", False),
            "created_at": user_data.get("created_at", "Unknown"),
            "last_login": last_login_str or "Never",
            "last_login_iso": last_login_str,
            "is_online": is_online,
            "total_sessions": user_data.get("total_sessions", 0),
            "total_duration": total_duration,
            "sessions": sessions[-10:],
            "welcome_bonus_given": user_data.get("welcome_bonus_given", False),
            "welcome_bonus_date": user_data.get("welcome_bonus_date"),
            "updated_at": user_data.get("updated_at", "Unknown")
        })
    
    # Sort by last login (most recent first), then by online status
    users_list.sort(key=lambda x: (
        x["is_online"],  # Online users first
        x["last_login"] or ""  # Then by last login
    ), reverse=True)
    
    return jsonify({
        "ok": True,
        "users": users_list,
        "total": len(users_list),
        "online_count": sum(1 for u in users_list if u["is_online"]),
        "offline_count": sum(1 for u in users_list if not u["is_online"])
    })

@app.get("/api/admin/stats")
@limiter.limit("100 per hour")
def get_admin_stats():
    """Get admin statistics."""
    verify_admin_token()
    users = load_users()
    
    total_users = len(users)
    total_talktime = sum(user.get("talktime", 0) for user in users.values())
    total_sessions = sum(user.get("total_sessions", 0) for user in users.values())
    
    # Users who logged in today
    today = datetime.now(timezone.utc).date()
    now = datetime.now(timezone.utc)
    
    active_today = 0
    online_now = 0
    
    for user in users.values():
        last_login_str = user.get("last_login")
        if last_login_str:
            try:
                if isinstance(last_login_str, str):
                    if last_login_str.endswith('Z'):
                        last_login_dt = datetime.fromisoformat(last_login_str.replace('Z', '+00:00'))
                    elif '+' in last_login_str or last_login_str.count('-') >= 3:
                        last_login_dt = datetime.fromisoformat(last_login_str)
                    else:
                        last_login_dt = datetime.fromisoformat(last_login_str.replace('Z', '') + '+00:00')
                else:
                    last_login_dt = last_login_str
                
                if last_login_dt:
                    # Ensure timezone aware
                    if last_login_dt.tzinfo is None:
                        login_date = last_login_dt.replace(tzinfo=timezone.utc)
                    else:
                        login_date = last_login_dt
                    
                    if login_date.date() == today:
                        active_today += 1
                    
                    # Online if last login within 15 minutes
                    time_diff = (now - login_date).total_seconds()
                    if time_diff < 900:
                        online_now += 1
            except Exception:
                pass
    
    return jsonify({
        "ok": True,
        "stats": {
            "total_users": total_users,
            "total_talktime": total_talktime,
            "total_sessions": total_sessions,
            "active_today": active_today,
            "online_now": online_now,
            "average_talktime": round(total_talktime / total_users, 2) if total_users > 0 else 0,
            "average_sessions": round(total_sessions / total_users, 2) if total_users > 0 else 0
        }
    })

@app.post("/api/admin/users/<email>/talktime")
@limiter.limit("100 per hour")
def update_user_talktime(email: str):
    """Update user talktime (admin only)."""
    verify_admin_token()
    
    if not validate_email(email):
        raise AppError("Invalid email address", status_code=400)
    
    data = request.get_json(silent=True) or {}
    action = data.get("action", "set")  # "add", "subtract", or "set"
    amount = int(data.get("amount", 0))
    
    if amount < 0:
        raise AppError("Amount cannot be negative", status_code=400)
    
    if action == "add":
        success = add_talktime_to_user(email, amount)
        message = f"Added {amount} seconds ({amount//60} minutes) of talktime to {email}"
    elif action == "subtract":
        success = add_talktime_to_user(email, -amount)
        message = f"Subtracted {amount} seconds ({amount//60} minutes) of talktime from {email}"
    elif action == "set":
        success = set_user_talktime(email, amount)
        message = f"Set talktime to {amount} seconds ({amount//60} minutes) for {email}"
    else:
        raise AppError("Invalid action. Use 'add', 'subtract', or 'set'", status_code=400)
    
    if success:
        user = get_user(email)
        return jsonify({
            "ok": True,
            "message": message,
            "new_talktime": user.get("talktime", 0) if user else 0,
            "new_talktime_minutes": round((user.get("talktime", 0) if user else 0) / 60, 2)
        })
    else:
        raise AppError("Failed to update talktime", status_code=500)

@app.delete("/api/admin/users/<email>")
@limiter.limit("50 per hour")
def delete_user_endpoint(email: str):
    """Delete user (admin only)."""
    verify_admin_token()
    
    if not validate_email(email):
        raise AppError("Invalid email address", status_code=400)
    
    if delete_user(email):
        return jsonify({
            "ok": True,
            "message": f"User {email} deleted successfully"
        })
    else:
        raise AppError("User not found or deletion failed", status_code=404)

@app.post("/api/admin/users/<email>/reset")
@limiter.limit("50 per hour")
def reset_user_data(email: str):
    """Reset user data (admin only)."""
    verify_admin_token()
    
    if not validate_email(email):
        raise AppError("Invalid email address", status_code=400)
    
    data = request.get_json(silent=True) or {}
    reset_type = data.get("type", "all")  # "talktime", "sessions", or "all"
    
    user = get_user(email)
    if not user:
        raise AppError("User not found", status_code=404)
    
    if reset_type == "talktime":
        update_user(email, {"talktime": 0})
        message = f"Reset talktime for {email}"
    elif reset_type == "sessions":
        update_user(email, {"sessions": [], "total_sessions": 0})
        message = f"Reset sessions for {email}"
    elif reset_type == "all":
        update_user(email, {"talktime": 0, "sessions": [], "total_sessions": 0})
        message = f"Reset all data for {email}"
    else:
        raise AppError("Invalid reset type. Use 'talktime', 'sessions', or 'all'", status_code=400)
    
    return jsonify({
        "ok": True,
        "message": message
    })

@app.post("/api/admin/users/<email>/reset-talktime")
@limiter.limit("50 per hour")
def reset_talktime_endpoint(email: str):
    """Instant reset of talktime to 0."""
    verify_admin_token()
    if not validate_email(email): raise AppError("Invalid email", status_code=400)
    
    set_user_talktime(email, 0)
    return jsonify({"ok": True, "message": f"Talktime reset for {email}"})

@app.post("/api/admin/users/<email>/toggle-vip")
@limiter.limit("50 per hour")
def toggle_vip_endpoint(email: str):
    """Toggle VIP/Community Member status."""
    verify_admin_token()
    if not validate_email(email): raise AppError("Invalid email", status_code=400)
    
    user = get_user(email)
    if not user: raise AppError("User not found", status_code=404)
    
    current_status = user.get("is_community_member", False)
    new_status = not current_status
    
    update_user(email, {
        "is_community_member": new_status,
        "last_community_refill": None if not new_status else user.get("last_community_refill")
    })
    
    status_msg = "Promoted to VIP" if new_status else "Removed from VIP"
    return jsonify({"ok": True, "message": f"{email} {status_msg}", "is_vip": new_status})

# ===== Application Startup =====
@app.post("/api/auth/google")
@limiter.limit("20 per hour")
def google_auth():
    """Handle Google Sign-In with server-side credential verification."""
    data = request.get_json(silent=True) or {}
    credential = data.get("credential", "").strip()
    
    if not credential:
        raise AppError("Google credential is required", status_code=400)
    
    if not Config.GOOGLE_CLIENT_ID:
        raise AppError("Google OAuth not configured", status_code=500)
    
    try:
        # Verify the Google credential server-side
        idinfo = id_token.verify_oauth2_token(
            credential,
            google_requests.Request(),
            Config.GOOGLE_CLIENT_ID
        )
        
        # Extract user information from verified token
        email = idinfo.get("email", "").strip().lower()
        name = idinfo.get("name", "").strip()
        
        if not email:
            raise AppError("Email not found in Google credential", status_code=400)
        
        # Check if user exists in Supabase
        user = get_user(email)
        
        if user:
            # Existing user: Update login time and name
            update_user(email, {
                "last_login": datetime.now(timezone.utc).isoformat(),
                "name": name or user.get("name")
            })
            logger.info(f"Google user logged in: {email}")
            
            # Generate app JWT token
            app_token = create_token(email)
            
            return jsonify({
                "ok": True,
                "message": "Login successful",
                "token": app_token,
                "email": email,
                "name": user.get("name") or name,
                "talktime": user.get("talktime", 0)
            })
        else:
            # New user: Create account with Welcome Bonus
            user_data = {
                "email": email,
                "name": name,
                "password_hash": None,  # Google users don't need a password
                "talktime": 180,        # 3 Minutes Free Bonus
                "created_at": datetime.now(timezone.utc).isoformat(),
                "last_login": datetime.now(timezone.utc).isoformat(),
                "sessions": [],
                "total_sessions": 0,
                "welcome_bonus_given": True,
                "welcome_bonus_date": datetime.now(timezone.utc).isoformat()
            }
            
            update_user(email, user_data)
            logger.info(f"New Google user signed up: {email}")
            
            # Generate app JWT token
            app_token = create_token(email)
            
            return jsonify({
                "ok": True,
                "message": "Account created successfully",
                "token": app_token,
                "email": email,
                "name": name,
                "talktime": 180
            })
            
    except ValueError as e:
        # Invalid token
        logger.warning(f"Invalid Google credential: {e}")
        raise AppError("Invalid Google credential", status_code=401)
    except Exception as e:
        logger.exception(f"Google authentication error: {e}")
        raise AppError("Google authentication failed", status_code=500)

if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("Starting Ronit AI Voice Coach Application")
    logger.info("=" * 60)
    logger.info(f"Environment: {Config.ENVIRONMENT}")
    logger.info(f"Debug Mode: {Config.DEBUG}")
    logger.info(f"Port: {Config.PORT}")
    
    logger.info("Email Configuration:")
    logger.info(f"  FROM_EMAIL: {Config.FROM_EMAIL}")
    logger.info(f"  FROM_NAME: {Config.FROM_NAME}")
    

    
    if Config.SMTP_HOST:
        logger.info(f"  SMTP: {Config.SMTP_HOST}:{Config.SMTP_PORT} (TLS: {Config.SMTP_TLS})")
    else:
        logger.info("  SMTP: Not configured")
    
    logger.info("API Configuration:")
    logger.info(f"  ElevenLabs: {'Configured' if Config.ELEVEN_API_KEY else 'Not configured'}")
    logger.info(f"  Gemini: {'Configured' if Config.GEMINI_API_KEY else 'Not configured'}")
    logger.info(f"  Razorpay: {'Configured' if Config.RAZORPAY_KEY_ID else 'Not configured'}")
    logger.info("=" * 60)
    
    app.run(
        host="0.0.0.0",
        port=Config.PORT,
        debug=Config.DEBUG,
        use_reloader=Config.DEBUG
    )
