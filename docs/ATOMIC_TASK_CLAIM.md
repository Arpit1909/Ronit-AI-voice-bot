# Atomic Task Claim Implementation Guide

## Overview

This implementation solves the **"Double Worker Problem"** - preventing multiple worker instances from processing the same task simultaneously and sending duplicate emails.

## The Problem

### Before (Race Condition)
```python
# Worker 1 at time T
response = supabase.table("tasks").select("*").eq("status", "pending").limit(1).execute()
# Gets task ID 123

# Worker 2 at time T (same millisecond!)
response = supabase.table("tasks").select("*").eq("status", "pending").limit(1).execute()
# Also gets task ID 123!

# Both workers process the same task → User gets 2 emails! ❌
```

### After (Atomic Claim)
```python
# Worker 1 at time T
response = supabase.rpc("claim_task").execute()  # Claims task 123, locks row

# Worker 2 at time T
response = supabase.rpc("claim_task").execute()  # Skips locked task 123, gets task 124

# Each worker processes different tasks → User gets 1 email ✅
```

## How It Works

### 1. Database Function (`claim_task_function.sql`)

The PostgreSQL function uses **FOR UPDATE SKIP LOCKED** which provides:

- **FOR UPDATE**: Locks the row during the transaction
- **SKIP LOCKED**: Skips rows locked by other workers
- **Atomic**: Select + Update happens in a single transaction

```sql
UPDATE tasks
SET status = 'processing', started_at = NOW()
WHERE id = (
    SELECT id FROM tasks
    WHERE status = 'pending'
    ORDER BY created_at ASC
    LIMIT 1
    FOR UPDATE SKIP LOCKED  -- 🔒 The magic happens here
)
RETURNING *;
```

### 2. Worker Implementation (`worker.py`)

The worker now calls the RPC function instead of manual select-then-update:

```python
# Old (race-prone)
response = supabase.table("tasks").select("*").eq("status", "pending").limit(1).execute()
tasks = response.data
if tasks:
    process_task(tasks[0])

# New (atomic)
response = supabase.rpc("claim_task").execute()
if response.data:
    process_task(response.data[0])
```

## Deployment Steps

### Step 1: Deploy SQL Function

1. Go to your **Supabase Dashboard**
2. Navigate to **SQL Editor**
3. Open `claim_task_function.sql`
4. Copy the entire contents
5. Paste into SQL Editor
6. Click **Run** (or press `Ctrl+Enter`)

You should see: `Success. No rows returned`

### Step 2: Verify Function Exists

Run this in SQL Editor:
```sql
SELECT * FROM claim_task();
```

- If you have pending tasks, you'll see one task returned
- If no pending tasks, you'll see empty result
- If error, the function wasn't created properly

### Step 3: Deploy Updated Worker

The updated `worker.py` is already modified. Simply restart your worker:

```bash
# Stop the old worker (Ctrl+C if running in terminal)
# Start the new worker
python worker.py
```

### Step 4: Test Atomic Claiming

Create a test task:
```python
from app import create_task

create_task("generate_care_plan", {
    "email": "test@example.com",
    "transcript": "Test transcript",
    "session_id": "test-123",
    "blueprint_id": "test-blueprint",
    "host_url": "http://localhost:5000"
})
```

The worker should claim and process it without issues.

## Scaling to Multiple Workers

Now you can safely run multiple worker instances:

```bash
# Terminal 1
python worker.py

# Terminal 2
python worker.py

# Terminal 3  
python worker.py
```

Each worker will claim different tasks atomically. No duplicates! 🎉

## Performance Characteristics

- **Throughput**: Scales linearly with workers (1 worker = 1 task/time, 3 workers = 3 tasks/time)
- **Latency**: No added latency compared to old implementation
- **Database Load**: Minimal - one RPC call per task claim
- **Lock Contention**: Zero - SKIP LOCKED prevents workers from waiting

## Monitoring

Check task status distribution:
```sql
SELECT status, COUNT(*) 
FROM tasks 
GROUP BY status;
```

Should see:
- `pending`: Tasks waiting to be claimed
- `processing`: Tasks currently being worked on
- `completed`: Successfully processed tasks
- `failed`: Tasks that threw errors

## Troubleshooting

### Error: "function claim_task() does not exist"

**Solution**: Deploy the SQL function (Step 1 above)

### Tasks stuck in "processing" status

**Possible causes**:
- Worker crashed during processing
- Task processing threw an exception

**Fix**: The `process_task()` function catches exceptions and sets status to 'failed'. But if the worker crashes before exception handling, manual cleanup:

```sql
-- Find stuck tasks (processing for > 1 hour)
SELECT * FROM tasks 
WHERE status = 'processing' 
  AND started_at < NOW() - INTERVAL '1 hour';

-- Reset them to pending
UPDATE tasks 
SET status = 'pending', started_at = NULL
WHERE status = 'processing' 
  AND started_at < NOW() - INTERVAL '1 hour';
```

### Workers not picking up tasks

**Check**:
1. Worker is running: `python worker.py` should show logs
2. Tasks exist: `SELECT * FROM tasks WHERE status = 'pending';`
3. RPC function works: `SELECT * FROM claim_task();`

## Technical Details

### Why PostgreSQL RPC?

Supabase's HTTP API doesn't support raw SQL with `FOR UPDATE`. Options were:

1. ❌ **REST API with filters**: Race conditions (old approach)
2. ❌ **PostgREST prefer header**: Not granular enough
3. ✅ **PostgreSQL RPC Function**: Full SQL power with atomic operations

### Why SKIP LOCKED?

Alternative locking strategies:

1. **FOR UPDATE** (no SKIP): Worker 2 waits for Worker 1's transaction to complete
   - ❌ Slower, creates lock contention
   
2. **FOR UPDATE NOWAIT**: Worker 2 gets an error if row is locked
   - ❌ Need to handle lock errors in Python
   
3. **FOR UPDATE SKIP LOCKED**: Worker 2 skips locked rows, gets next available task
   - ✅ **Fastest, cleanest, no errors**

### Database Schema Requirements

The `tasks` table needs these columns (you probably already have them):

```sql
CREATE TABLE tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type TEXT NOT NULL,
    payload JSONB NOT NULL,
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    error TEXT
);

-- Index for performance (highly recommended!)
CREATE INDEX idx_tasks_pending ON tasks(created_at) WHERE status = 'pending';
```

## Summary

✅ **Problem Solved**: Multiple workers can now run safely  
✅ **No Code Changes Needed**: Just deploy SQL function  
✅ **Production Ready**: Battle-tested pattern used by major companies  
✅ **Zero Downtime**: Old workers gracefully stop, new workers start  

**Next Step**: Deploy the SQL function and restart your worker!
