-- ===== Supabase Database Migration for Ronit AI Voice Coach =====
-- Run this SQL in your Supabase SQL Editor to create the users table

-- Create users table
CREATE TABLE IF NOT EXISTS users (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT,
    talktime INTEGER DEFAULT 0 NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    last_login TIMESTAMPTZ,
    sessions JSONB DEFAULT '[]'::jsonb,
    total_sessions INTEGER DEFAULT 0 NOT NULL,
    welcome_bonus_given BOOLEAN DEFAULT FALSE NOT NULL,
    welcome_bonus_date TIMESTAMPTZ
);

-- Create index on email for faster lookups
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

-- Create index on created_at for sorting
CREATE INDEX IF NOT EXISTS idx_users_created_at ON users(created_at DESC);

-- Create index on last_login for active user queries
CREATE INDEX IF NOT EXISTS idx_users_last_login ON users(last_login DESC);

-- Enable Row Level Security (RLS) - Optional, adjust based on your needs
ALTER TABLE users ENABLE ROW LEVEL SECURITY;

-- Create policy to allow service role to do everything (for backend operations)
-- Note: Adjust this based on your security requirements
CREATE POLICY "Service role can manage users" ON users
    FOR ALL
    USING (true)
    WITH CHECK (true);

-- Create a function to automatically update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Create trigger to auto-update updated_at
CREATE TRIGGER update_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Optional: Create a view for user statistics
CREATE OR REPLACE VIEW user_stats AS
SELECT 
    COUNT(*) as total_users,
    SUM(talktime) as total_talktime,
    SUM(total_sessions) as total_sessions,
    COUNT(CASE WHEN last_login >= CURRENT_DATE THEN 1 END) as active_today
FROM users;
