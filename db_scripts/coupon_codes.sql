-- Run this in Supabase SQL Editor to create the coupon_codes table

CREATE TABLE IF NOT EXISTS public.coupon_codes (
    code        TEXT PRIMARY KEY,
    max_uses    INTEGER DEFAULT NULL,   -- NULL = unlimited
    uses        INTEGER DEFAULT 0,
    is_active   BOOLEAN DEFAULT TRUE,
    expires_at  TIMESTAMPTZ DEFAULT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Index for fast lookups
CREATE INDEX IF NOT EXISTS idx_coupon_codes_active ON public.coupon_codes(code, is_active);
