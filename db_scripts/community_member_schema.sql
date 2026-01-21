-- ==========================================
-- Community Member System - Database Schema
-- ==========================================
-- Run this in your Supabase SQL Editor before deploying the code changes
-- ==========================================

-- 1. Add Community Member columns to users table
ALTER TABLE public.users
ADD COLUMN IF NOT EXISTS is_community_member BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS last_community_refill TIMESTAMPTZ;

-- 2. Create index for faster queries on community members
CREATE INDEX IF NOT EXISTS idx_users_community 
ON public.users(is_community_member) 
WHERE is_community_member = TRUE;

-- 3. Add comment for documentation
COMMENT ON COLUMN public.users.is_community_member IS 'VIP status - receives 15 mins free every 30 days';
COMMENT ON COLUMN public.users.last_community_refill IS 'Timestamp of last automatic refill for community members';

-- ==========================================
-- VERIFICATION QUERIES
-- ==========================================

-- Check if columns were added successfully
SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_name = 'users' 
  AND column_name IN ('is_community_member', 'last_community_refill');

-- Count current community members (should be 0 initially)
SELECT COUNT(*) as total_community_members
FROM public.users
WHERE is_community_member = TRUE;

-- ==========================================
-- TESTING (Optional)
-- ==========================================

-- Test: Add a test community member (replace with actual email)
-- UPDATE public.users
-- SET is_community_member = TRUE
-- WHERE email = 'test@example.com';

-- Test: Check if refill logic would trigger (simulate 31 days ago)
-- UPDATE public.users
-- SET last_community_refill = NOW() - INTERVAL '31 days'
-- WHERE email = 'test@example.com';

-- ==========================================
-- ROLLBACK (If needed - use with caution)
-- ==========================================

-- To remove community member features:
-- ALTER TABLE public.users DROP COLUMN IF EXISTS is_community_member;
-- ALTER TABLE public.users DROP COLUMN IF EXISTS last_community_refill;
-- DROP INDEX IF EXISTS idx_users_community;
