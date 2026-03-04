#!/usr/bin/env python3
"""
Database migration script using Alembic
"""
import os
import sys
import time
from alembic.config import Config
from alembic import command
from sqlalchemy import create_engine, text
from app.config import settings

def wait_for_db(max_retries=30, delay=1):
    """Wait for database to be ready"""
    engine = create_engine(settings.database_url)
    
    for attempt in range(max_retries):
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            print("✅ Database is ready!")
            return True
        except Exception as e:
            print(f"⏳ Waiting for database... (attempt {attempt + 1}/{max_retries})")
            print(f"   Error: {e}")
            time.sleep(delay)
    
    print("❌ Database is not ready after maximum retries")
    return False

def run_migrations():
    """Run Alembic migrations"""
    try:
        print("🔧 Running database migrations...")
        
        # Create Alembic configuration
        alembic_cfg = Config()
        alembic_cfg.set_main_option("script_location", "app/migrations")
        alembic_cfg.set_main_option("sqlalchemy.url", settings.database_url)
        
        # Run migrations
        command.upgrade(alembic_cfg, "head")
        print("✅ Database migrations completed successfully!")
        return True
    except Exception as e:
        print(f"❌ Error running migrations: {e}")
        return False

def create_migration(message):
    """Create a new migration"""
    try:
        print(f"🔧 Creating migration: {message}")
        
        # Create Alembic configuration
        alembic_cfg = Config()
        alembic_cfg.set_main_option("script_location", "app/migrations")
        alembic_cfg.set_main_option("sqlalchemy.url", settings.database_url)
        
        # Create migration
        command.revision(alembic_cfg, autogenerate=True, message=message)
        print("✅ Migration created successfully!")
        return True
    except Exception as e:
        print(f"❌ Error creating migration: {e}")
        return False

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "create":
        # Create a new migration
        message = sys.argv[2] if len(sys.argv) > 2 else "Auto-generated migration"
        if not wait_for_db():
            sys.exit(1)
        if not create_migration(message):
            sys.exit(1)
    else:
        # Run migrations
        print("🚀 Starting database migration...")
        
        if not wait_for_db():
            sys.exit(1)
        
        if not run_migrations():
            sys.exit(1)
        
        print("🎉 Database migration completed!")
