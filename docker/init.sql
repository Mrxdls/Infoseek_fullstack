-- PostgreSQL initialization script
-- Runs automatically on first container start

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Enable pg_trgm for text search (optional but useful)
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Grant all privileges to app user
GRANT ALL PRIVILEGES ON DATABASE ragapp TO raguser;
