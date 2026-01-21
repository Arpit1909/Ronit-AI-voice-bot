import multiprocessing
import os

# Gunicorn Configuration for Ronit AI Coach

# Bind to localhost on port 5000 (Caddy will proxy to this)
bind = "127.0.0.1:5000"

# --- SCALING CONFIGURATION ---
# Since we now use Redis for shared session state, we can run multiple workers!
# Rule of thumb: (2 x CPU Cores) + 1
workers = multiprocessing.cpu_count() * 2 + 1
threads = 4  # Reduced threads per worker since we have more workers
worker_class = "gthread"

# --- CONNECTION LIMITS ---
# worker_connections = 1000 # Gthread doesn't use this the same way eventlet does

# Timeout Configuration
# ElevenLabs WebSocket connections can be long-lived
timeout = 120
keepalive = 5

# Logging
accesslog = "-"  # Log to stdout
errorlog = "-"   # Log to stderr
loglevel = "info"

# Process Naming
proc_name = "ronit-ai-coach"

# Reload in development (optional, disabled for production stability)
reload = False

# Environment Variables (can be overridden by system env)
raw_env = [
    "FLASK_ENV=production",
    "PYTHONUNBUFFERED=1"
]
