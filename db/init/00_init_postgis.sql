-- Runs only when the database volume is empty on first start.
-- Ensures PostGIS is available; harmless if already present.
CREATE EXTENSION IF NOT EXISTS postgis;

-- Create common schemas used by your app (no-op if they exist).
CREATE SCHEMA IF NOT EXISTS gracethd;
CREATE SCHEMA IF NOT EXISTS resilience;
