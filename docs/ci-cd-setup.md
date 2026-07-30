# GitLab CI/CD Test Pipeline

## Overview

The GitLab CI/CD pipeline runs all tests automatically on every push to ensure code quality and prevent regressions.

## Jobs

### backend-tests
- **Stage:** test
- **Environment:** Python 3.11 + PostgreSQL 15
- **Command:** `pytest -v --tb=short`
- **Dependencies:** All files in `backend/` directory
- **What it tests:** Business logic, API endpoints, database models, sync services

### frontend-tests
- **Stage:** test
- **Environment:** Node.js 18
- **Command:** `npm test` (Vitest)
- **Dependencies:** All files in `frontend/` directory
- **What it tests:** React components, UI logic, routing

## Running Tests Locally

### Backend
```bash
cd backend
pip install -r requirements-dev.txt
pytest -v
```

### Frontend
```bash
cd frontend
npm install
npm test
```

## Viewing Results

After pushing to GitLab, navigate to your repository → **CI/CD** → **Pipelines** to see:
- Individual job logs
- Test result reports
- Failure details and stack traces

## Troubleshooting

### Backend tests fail with "database connection refused"
Ensure PostgreSQL is running if testing locally. In CI/CD, the postgres service is automatically started.

### Frontend tests timeout
If npm install takes too long, check npm registry connectivity. Consider using a faster npm mirror if needed.

### Tests pass locally but fail in CI/CD
Common causes:
- Missing environment variables (check `.env.example` vs CI setup)
- Database state differences (CI uses fresh DB each run)
- Node/Python version differences
