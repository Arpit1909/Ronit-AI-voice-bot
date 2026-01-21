-- ============================================================================
-- Complete Database Setup for Worker & Payment Systems
-- ============================================================================
-- Run this entire script in your Supabase SQL Editor (Dashboard)
-- This creates all necessary tables and the atomic task claiming function
-- ============================================================================

-- 1. Create TASKS table for the background worker
CREATE TABLE IF NOT EXISTS public.tasks (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    type TEXT NOT NULL,
    payload JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending', -- pending, processing, completed, failed
    created_at TIMESTAMPTZ DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    error TEXT
);

-- Index for fast worker polling
CREATE INDEX IF NOT EXISTS idx_tasks_status_created ON public.tasks (status, created_at) WHERE status = 'pending';

-- 2. Create TRANSACTIONS table for payment security (Anti-Replay)
CREATE TABLE IF NOT EXISTS public.transactions (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    order_id TEXT UNIQUE NOT NULL, -- Razorpay Order ID
    email TEXT NOT NULL,
    amount INTEGER NOT NULL, -- In paisa
    status TEXT DEFAULT 'success',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for fast replay checks
CREATE INDEX IF NOT EXISTS idx_transactions_order_id ON public.transactions (order_id);

-- 3. Create the Atomic Task Claim Function (The "God Mode" Lock)
CREATE OR REPLACE FUNCTION claim_next_task()
RETURNS SETOF public.tasks
LANGUAGE plpgsql
AS $$
DECLARE
  _task_id uuid;
BEGIN
  -- Find next pending task and lock it (SKIP LOCKED prevents race conditions)
  SELECT id INTO _task_id
  FROM public.tasks
  WHERE status = 'pending'
  ORDER BY created_at ASC
  LIMIT 1
  FOR UPDATE SKIP LOCKED;

  -- If found, mark processing and return it
  IF _task_id IS NOT NULL THEN
    RETURN QUERY
    UPDATE public.tasks
    SET status = 'processing', started_at = NOW()
    WHERE id = _task_id
    RETURNING *;
  END IF;
END;
$$;

-- ============================================================================
-- DEPLOYMENT INSTRUCTIONS
-- ============================================================================
-- 1. Go to your Supabase Dashboard: https://app.supabase.com
-- 2. Select your project
-- 3. Navigate to "SQL Editor" in the left sidebar
-- 4. Copy and paste this ENTIRE file
-- 5. Click "Run" (or press Ctrl+Enter)
-- 6. You should see: "Success. No rows returned"
-- 
-- VERIFICATION:
-- Run these queries to verify everything was created:
--   SELECT * FROM public.tasks LIMIT 1;
--   SELECT * FROM public.transactions LIMIT 1;
--   SELECT claim_next_task();
-- 
-- If no errors, your database is ready! ✅
-- ============================================================================
