-- ==========================================
-- Pending Community Members - Database Schema
-- ==========================================
-- Run this in your Supabase SQL Editor
-- ==========================================

-- Create table for pending community members (users pre-approved but not yet signed up)
CREATE TABLE IF NOT EXISTS public.pending_community_members (
    email TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    created_by TEXT, -- Admin email who added this
    notes TEXT -- Optional notes
);

-- Create index for faster lookups
CREATE INDEX IF NOT EXISTS idx_pending_community_email 
ON public.pending_community_members(email);

-- Add comment for documentation
COMMENT ON TABLE public.pending_community_members IS 'Emails pre-approved for community member status. When these users sign up, they automatically become community members.';

-- ==========================================
-- VERIFICATION QUERIES
-- ==========================================

-- Check if table was created successfully
SELECT table_name, column_name, data_type
FROM information_schema.columns
WHERE table_name = 'pending_community_members';

-- Count pending community members
SELECT COUNT(*) as total_pending
FROM public.pending_community_members;
