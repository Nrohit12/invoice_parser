# FastAPI + Docker + Redis + Celery + PostgreSQL Setup

A complete setup for FastAPI with Celery background tasks, Redis as message broker, PostgreSQL database, and Docker containerization.

## Features

- **FastAPI**: Modern, fast web framework for building APIs
- **Celery**: Distributed task queue for background processing
- **Redis**: In-memory data store used as message broker and result backend
- **PostgreSQL**: Relational database for persistent data storage
- **Docker**: Containerized deployment with docker-compose
- **Environment Configuration**: `.env` based configuration management
- **Flower**: Web-based tool for monitoring Celery tasks
- **Health Checks**: Comprehensive health monitoring for all services

## Project Structure

```
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI application
│   ├── celery_app.py        # Celery configuration
│   ├── config.py            # Settings and configuration
│   ├── database.py          # Database models and connection
│   ├── init_db.py           # Database initialization script
│   └── tasks/
│       ├── __init__.py
│       └── tasks.py         # Celery tasks
├── docker-compose.yml       # Docker services configuration
├── Dockerfile              # Docker image definition
├── requirements.txt        # Python dependencies
├── .env.example           # Environment variables template
├── .env                   # Environment variables (create from .env.example)
└── README.md             # This file
```

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Python 3.11+ (for local development)

### Setup

1. **Clone and navigate to the project directory**

2. **Create environment file**
   ```bash
   cp .env.example .env
   ```

3. **Start all services with Docker Compose**
   ```bash
   docker-compose up --build
   ```

4. **Access the services**
   - FastAPI API: http://localhost:8000
   - API Documentation: http://localhost:8000/docs
   - Flower (Celery monitoring): http://localhost:5555
   - PostgreSQL: localhost:5432
   - Redis: localhost:6379

## API Endpoints

### Health Check
- `GET /` - Basic API information
- `GET /health` - Health check for all services (API, Database, Redis, Celery)

### Task Management
- `POST /tasks/long-running` - Create a long-running task
- `POST /tasks/add` - Create an addition task
- `POST /tasks/notification` - Create a notification task
- `GET /tasks/{task_id}` - Get task status and result
- `DELETE /tasks/{task_id}` - Cancel a task
- `GET /tasks` - List active and scheduled tasks

### Example API Calls

**Health Check:**
```bash
curl "http://localhost:8000/health"
```

**Create a long-running task:**
```bash
curl -X POST "http://localhost:8000/tasks/long-running" \
     -H "Content-Type: application/json" \
     -d '{"duration": 15}'
```

**Create an addition task:**
```bash
curl -X POST "http://localhost:8000/tasks/add" \
     -H "Content-Type: application/json" \
     -d '{"x": 10, "y": 20}'
```

**Check task status:**
```bash
curl "http://localhost:8000/tasks/{task_id}"
```

## Services

### PostgreSQL Database
- **Image**: postgres:15-alpine
- **Port**: 5432
- **Database**: fastapi_db
- **User**: postgres
- **Password**: postgres (configurable via .env)

### Redis
- **Image**: redis:7-alpine
- **Port**: 6379
- **Persistence**: Enabled with appendonly mode

### FastAPI Application
- **Port**: 8000
- **Auto-reload**: Enabled in development
- **Health checks**: Database, Redis, and Celery connectivity

### Celery Worker
- **Tasks**: Background job processing
- **Broker**: Redis
- **Result Backend**: Redis

### Flower
- **Port**: 5555
- **Purpose**: Celery task monitoring and management

## Local Development

### Without Docker

1. **Install PostgreSQL and Redis locally**
   ```bash
   # macOS
   brew install postgresql redis
   brew services start postgresql
   brew services start redis
   
   # Ubuntu
   sudo apt-get install postgresql postgresql-contrib redis-server
   sudo systemctl start postgresql
   sudo systemctl start redis
   ```

2. **Create database**
   ```bash
   createdb fastapi_db
   ```

3. **Install Python dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Update .env file for local development**
   ```env
   DATABASE_URL=postgresql://postgres:postgres@localhost:5432/fastapi_db
   REDIS_HOST=localhost
   CELERY_BROKER_URL=redis://localhost:6379/0
   CELERY_RESULT_BACKEND=redis://localhost:6379/0
   ```

5. **Initialize database**
   ```bash
   python app/init_db.py
   ```

6. **Start the services**
   ```bash
   # Terminal 1: Start FastAPI
   uvicorn app.main:app --reload
   
   # Terminal 2: Start Celery worker
   celery -A app.celery_app worker --loglevel=info
   
   # Terminal 3: Start Flower (optional)
   celery -A app.celery_app flower
   ```

## Configuration

All configuration is managed through environment variables defined in `.env`:

### Database Settings
- `POSTGRES_USER`: Database user
- `POSTGRES_PASSWORD`: Database password
- `POSTGRES_DB`: Database name
- `POSTGRES_HOST`: Database host
- `POSTGRES_PORT`: Database port
- `DATABASE_URL`: Complete database connection string

### Redis Settings
- `REDIS_HOST`: Redis host
- `REDIS_PORT`: Redis port
- `REDIS_DB`: Redis database number
- `REDIS_PASSWORD`: Redis password (optional)

### Celery Settings
- `CELERY_BROKER_URL`: Message broker URL
- `CELERY_RESULT_BACKEND`: Result backend URL

### API Settings
- `API_HOST`: FastAPI host
- `API_PORT`: FastAPI port
- `DEBUG`: Debug mode

### App Settings
- `APP_NAME`: Application name
- `APP_VERSION`: Application version

## Monitoring

- **Health Endpoint**: Use `/health` to check all service connectivity
- **Flower Dashboard**: Access at http://localhost:5555 to monitor Celery tasks
- **Logs**: View container logs with `docker-compose logs [service_name]`
- **Database**: Connect directly to PostgreSQL on port 5432

## Database

The setup includes a basic SQLAlchemy model (`TaskResult`) for storing task results. Database schema is managed using **Alembic migrations**.

### Database Migrations

The project uses Alembic for database schema management. Migrations are automatically run when the application starts via Docker Compose.

#### Migration Commands

**Create a new migration:**
```bash
# Using the migration script
python migrate.py create "Description of changes"

# Or using Alembic directly
alembic -c app/migrations/alembic.ini revision --autogenerate -m "Description of changes"
```

**Run migrations:**
```bash
# Using the migration script
python migrate.py

# Or using Alembic directly
alembic -c app/migrations/alembic.ini upgrade head
```

**Check migration status:**
```bash
alembic -c app/migrations/alembic.ini current
alembic -c app/migrations/alembic.ini history
```

### Database Schema

The current schema includes:

```sql
CREATE TABLE task_results (
    id SERIAL PRIMARY KEY,
    task_id VARCHAR UNIQUE NOT NULL,
    task_name VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    result TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE
);
```

## Scaling

To scale Celery workers:
```bash
docker-compose up --scale celery_worker=3
```

To scale the API:
```bash
docker-compose up --scale api=2
```

## Stopping Services

```bash
docker-compose down
```

To remove volumes as well:
```bash
docker-compose down -v
```

## Troubleshooting

1. **Database connection issues**: 
   - Check if PostgreSQL container is running
   - Verify DATABASE_URL in .env file
   - Check database credentials

2. **Redis connection issues**: 
   - Check if Redis container is running and accessible
   - Verify REDIS_HOST and REDIS_PORT in .env

3. **Celery tasks not executing**: 
   - Verify Celery worker is running and connected to Redis
   - Check Flower dashboard for worker status

4. **Port conflicts**: 
   - Ensure ports 8000, 5432, 6379, and 5555 are available
   - Modify port mappings in docker-compose.yml if needed

5. **Environment variables**: 
   - Verify `.env` file exists and contains correct values
   - Check that all required environment variables are set

## Adding New Tasks

1. Define your task in `app/tasks/tasks.py`:
   ```python
   @celery_app.task
   def my_new_task(param1, param2):
       # Your task logic here
       return {"result": "success"}
   ```

2. Add an endpoint in `app/main.py` to trigger the task:
   ```python
   @app.post("/tasks/my-new-task")
   async def create_my_new_task(request: MyTaskRequest):
       task = my_new_task.delay(request.param1, request.param2)
       return {"task_id": task.id, "status": "started"}
   ```

3. Restart the services to load the new task.

## Docker Services

The application consists of the following services:

1. **migrate**: Runs database migrations before other services start
2. **api**: FastAPI application server
3. **celery_worker**: Background task processor
4. **celery_flower**: Task monitoring dashboard
5. **postgres**: PostgreSQL database
6. **redis**: Message broker and cache

### Service Dependencies

```
postgres (healthy) → migrate (completed) → api, celery_worker
redis (healthy) → api, celery_worker, celery_flower
```

## Security Considerations

- Change default passwords in production
- Use environment-specific .env files
- Implement proper authentication and authorization
- Use SSL/TLS for database connections in production
- Regularly update dependencies for security patches
