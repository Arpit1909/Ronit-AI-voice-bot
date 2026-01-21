import os
import time
import json
import logging
import threading
from datetime import datetime, timezone
from dotenv import load_dotenv
from supabase import create_client
from app import app, _call_gemini_mindmap_blueprint, save_blueprint_to_disk, record_user_session, _delayed_email_with_link, Config, logger

# Initialize Supabase independently to avoid circular issues or context confusion
load_dotenv()
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")
supabase = create_client(supabase_url, supabase_key)

logger.setLevel(logging.INFO)
logger.info("👷 Background Worker Started")

def process_task(task):
    task_id = task['id']
    payload = task['payload']
    task_type = task['type']
    
    logger.info(f"Processing task {task_id} [{task_type}]")
    
    try:
        # Note: Status already set to 'processing' by claim_task() RPC function
        # and started_at timestamp already recorded there as well.
        
        if task_type == "generate_care_plan":
            email = payload['email']
            transcript = payload['transcript']
            session_id = payload['session_id']
            blueprint_id = payload['blueprint_id']
            host_url = payload['host_url']
            
            # 1. Calls Gemini
            care_plan = _call_gemini_mindmap_blueprint(transcript)
            
            # 2. Save Blueprint
            blueprint_data = {
                "content": care_plan,
                "email": email,
                "created": datetime.now(timezone.utc).isoformat(),
                "session_id": session_id,
                "transcript": transcript
            }
            save_blueprint_to_disk(blueprint_id, blueprint_data)
            
            # 3. Record Session
            try:
                record_user_session(email, {
                    "session_id": session_id,
                    "duration": len(transcript) // 100,
                    "transcript_length": len(transcript)
                })
            except Exception as e:
                logger.warning(f"Failed to record session stats: {e}")
                
            # 4. Email
            care_plan_link = f"{host_url.rstrip('/')}/blueprint/{blueprint_id}"
            # Send immediately (0 delay) with care plan content included
            _delayed_email_with_link(email, care_plan_link, care_plan, 0)
            
        # Update status to completed
        supabase.table("tasks").update({
            "status": "completed",
            "completed_at": datetime.now(timezone.utc).isoformat()
        }).eq("id", task_id).execute()
        
        logger.info(f"✅ Task {task_id} completed successfully")
        
    except Exception as e:
        logger.exception(f"❌ Task {task_id} failed: {e}")
        supabase.table("tasks").update({
            "status": "failed",
            "error": str(e)
        }).eq("id", task_id).execute()

def worker_loop():
    logger.info("👷 Worker started polling...")
    while True:
        try:
            # CALL THE ATOMIC DB FUNCTION
            # This ensures even if you run 100 workers, a task is processed EXACTLY once.
            response = supabase.rpc("claim_next_task", {}).execute()
            
            # The RPC returns a list (because it's a table set), take the first one
            if response.data and len(response.data) > 0:
                task = response.data[0]
                process_task(task)
            else:
                # No tasks found, sleep to save CPU
                time.sleep(2) 
                
        except Exception as e:
            logger.error(f"Worker loop error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    # Ensure app context is pushed if needed (e.g. for logging setup)
    with app.app_context():
        worker_loop()
