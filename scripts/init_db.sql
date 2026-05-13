-- Initialize PostgreSQL extensions for RAG healthcare assistant
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Indexes are created by the application on startup (see app/db/database.py init_db).
