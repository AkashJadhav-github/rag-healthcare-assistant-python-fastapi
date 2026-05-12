-- Initialize PostgreSQL extensions for RAG healthcare assistant
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Create optimized GIN index on document_chunks content for keyword search
-- (applied after table creation by the application via Alembic)
