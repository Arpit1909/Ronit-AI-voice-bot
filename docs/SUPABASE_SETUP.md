# 🚀 Supabase Database Setup - Quick Guide

## What This SQL Does

This script creates the "brain" for your worker and payment systems:

1. **`tasks` table** - Stores background tasks for email sending and AI processing
2. **`transactions` table** - Prevents payment replay attacks (duplicate charges)
3. **`claim_next_task()` function** - Atomic task claiming (prevents double worker problem)

---

## Step-by-Step Deployment

### 1. Open Supabase SQL Editor

1. Go to: https://app.supabase.com
2. Select your project
3. Click **"SQL Editor"** in the left sidebar

### 2. Run the SQL Script

1. Open [`claim_task_function.sql`](file:///d:/Arpit%20Sharma/Desktop/Ronit-AI-Model-main/claim_task_function.sql)
2. **Select ALL** text (Ctrl+A)
3. **Copy** (Ctrl+C)
4. Go back to Supabase SQL Editor
5. **Paste** (Ctrl+V)
6. Click **"Run"** button (or press Ctrl+Enter)

### 3. Verify Success

You should see:
```
Success. No rows returned
```

If you see errors, they're likely:
- ❌ "relation already exists" - Tables already created (this is OK!)
- ❌ "permission denied" - Check your Supabase role has permissions

### 4. Test the Setup

Run these verification queries in SQL Editor:

```sql
-- Test 1: Check tasks table exists
SELECT * FROM public.tasks LIMIT 1;

-- Test 2: Check transactions table exists  
SELECT * FROM public.transactions LIMIT 1;

-- Test 3: Test atomic claim function
SELECT * FROM claim_next_task();
```

**Expected Results:**
- Test 1 & 2: Empty result (no rows) or existing data ✅
- Test 3: Empty result (no pending tasks yet) ✅

If any query returns an error, the table/function wasn't created properly.

---

## What Each Table Does

### `tasks` Table

Stores background work items for the worker to process.

**Schema:**
```sql
id           UUID        -- Unique task ID
type         TEXT        -- Task type (e.g., "generate_care_plan")
payload      JSONB       -- Task data (email, transcript, etc.)
status       TEXT        -- pending → processing → completed/failed
created_at   TIMESTAMPTZ -- When task was created
started_at   TIMESTAMPTZ -- When worker claimed it
completed_at TIMESTAMPTZ -- When worker finished
error        TEXT        -- Error message if failed
```

**Status Flow:**
```
pending → processing → completed ✅
                    → failed ❌
```

### `transactions` Table

Prevents payment replay attacks (charging the same order twice).

**Schema:**
```sql
id         UUID    -- Unique transaction ID
order_id   TEXT    -- Razorpay order ID (UNIQUE constraint)
email      TEXT    -- User email
amount     INTEGER -- Amount in paisa
status     TEXT    -- Payment status
created_at TIMESTAMPTZ
```

**How It Prevents Replay Attacks:**
1. User purchases talktime → Razorpay order created
2. Payment succeeds → Order ID saved to `transactions`
3. If webhook fires again (duplicate) → `order_id` already exists → Reject ✅

### `claim_next_task()` Function

The atomic "brain" that prevents race conditions.

**What It Does:**
```sql
1. SELECT id FROM tasks WHERE status = 'pending' 
   ORDER BY created_at ASC LIMIT 1 
   FOR UPDATE SKIP LOCKED;  -- 🔒 The magic line

2. If found:
   UPDATE tasks SET status = 'processing', started_at = NOW()
   WHERE id = _task_id
   RETURNING *;
```

**Why SKIP LOCKED?**
- Worker 1 calls `claim_next_task()` → Locks task #101
- Worker 2 calls at same time → Skips #101 (locked), gets #102
- Zero race conditions, even with 100 workers! 🚀

---

## Common Issues

### ❌ "Permission denied for schema public"

**Fix:** Your Supabase user needs permissions. Run:
```sql
GRANT USAGE ON SCHEMA public TO postgres;
GRANT ALL ON ALL TABLES IN SCHEMA public TO postgres;
GRANT ALL ON ALL FUNCTIONS IN SCHEMA public TO postgres;
```

### ❌ "Relation 'tasks' already exists"

**Not an error!** Tables already created. You're good! ✅

### ❌ "Function claim_next_task() does not exist"

**Fix:** The function creation failed. Check for SQL syntax errors and re-run just the function part:

```sql
CREATE OR REPLACE FUNCTION claim_next_task()
RETURNS SETOF public.tasks
LANGUAGE plpgsql
AS $$
DECLARE
  _task_id uuid;
BEGIN
  SELECT id INTO _task_id
  FROM public.tasks
  WHERE status = 'pending'
  ORDER BY created_at ASC
  LIMIT 1
  FOR UPDATE SKIP LOCKED;

  IF _task_id IS NOT NULL THEN
    RETURN QUERY
    UPDATE public.tasks
    SET status = 'processing', started_at = NOW()
    WHERE id = _task_id
    RETURNING *;
  END IF;
END;
$$;
```

---

## After Running SQL

### Start Your Worker

```bash
python worker.py
```

You should see:
```
👷 Worker started polling...
```

### Test Creating a Task

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

Worker should immediately claim and process it!

### Monitor in Supabase Dashboard

1. Go to **"Table Editor"** → **tasks**
2. Refresh to see tasks appearing
3. Watch status change: `pending` → `processing` → `completed`

---

## Database Ready Checklist

- [ ] ✅ SQL script executed in Supabase without errors
- [ ] ✅ Verified tables exist (`tasks`, `transactions`)
- [ ] ✅ Verified function exists (`claim_next_task()`)
- [ ] ✅ Worker starts without errors
- [ ] ✅ Test task created and processed

---

## Next Steps

1. **Deploy Worker** - Can now run multiple workers safely
2. **Deploy JWT_SECRET_KEY** - Add to production environment variables
3. **Deploy Frontend** - Updated `script.js` with iOS audio fix

See [`PRODUCTION_READINESS.md`](file:///d:/Arpit%20Sharma/Desktop/Ronit-AI-Model-main/PRODUCTION_READINESS.md) for complete deployment guide.

---

**Your database is now the "brain" of your production system!** 🧠✨
