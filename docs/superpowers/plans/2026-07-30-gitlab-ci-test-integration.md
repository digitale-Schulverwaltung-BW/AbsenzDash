# GitLab CI/CD Test Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate backend (pytest) and frontend (vitest) tests into GitLab CI/CD pipeline to automatically run on every push.

**Architecture:** GitLab CI/CD pipeline with two independent job stages — one for backend tests (using Docker with PostgreSQL service) and one for frontend tests (using Node.js). Tests run in parallel, with clear pass/fail reporting. No manual intervention required after push.

**Tech Stack:** GitLab CI/CD, Docker (backend), Node.js/npm (frontend), pytest, vitest

## Global Constraints

- Backend Python version: 3.11 (from Dockerfile)
- Frontend Node version: 18+ (standard for modern React/Vite projects)
- Tests must run without requiring external WebUntis API calls (use mocks)
- Test database: PostgreSQL 15-alpine (from docker-compose.yml)
- All tests must pass before merge (no optional failures)

---

## File Structure

| File | Responsibility |
|------|-----------------|
| `.gitlab-ci.yml` | Main CI/CD pipeline definition with stages, jobs, and dependencies |

## Task 1: Create `.gitlab-ci.yml` with Backend Test Job

**Files:**
- Create: `.gitlab-ci.yml`

**Interfaces:**
- Produces: GitLab CI/CD pipeline configuration with backend pytest job

**Steps:**

- [ ] **Step 1: Create `.gitlab-ci.yml` with backend test job**

Create the file at project root with the following content:

```yaml
stages:
  - test

# Backend tests using Python 3.11 + PostgreSQL
backend-tests:
  stage: test
  image: python:3.11-slim
  services:
    - postgres:15-alpine
  variables:
    POSTGRES_USER: "absenzdash"
    POSTGRES_PASSWORD: "absenzdash"
    POSTGRES_DB: "absenzdash"
    POSTGRES_HOST_AUTH_METHOD: "trust"
    DATABASE_URL: "postgresql://absenzdash:absenzdash@postgres:5432/absenzdash"
  before_script:
    - apt-get update && apt-get install -y --no-install-recommends
        libpango-1.0-0
        libpangocairo-1.0-0
        libcairo2
        libgdk-pixbuf-2.0-0
        libffi-dev
        shared-mime-info
        fonts-liberation
    - cd backend
    - pip install --no-cache-dir -r requirements-dev.txt
  script:
    - pytest -v --tb=short
  artifacts:
    reports:
      junit: backend/test-results.xml
    when: always
  retry:
    max: 1
    when:
      - runner_system_failure
      - stuck_or_timeout_failure
```

- [ ] **Step 2: Verify the YAML is syntactically correct**

Run:
```bash
cd /Users/seyfried/Documents/src/AbsenzDash
yamllint .gitlab-ci.yml
```

If `yamllint` is not available, just check manually that indentation is correct (2-space, no tabs).

Expected: No syntax errors reported.

- [ ] **Step 3: Commit the backend test job**

```bash
git add .gitlab-ci.yml
git commit -m "ci: add backend pytest job to GitLab CI/CD pipeline"
```

---

## Task 2: Add Frontend Test Job to `.gitlab-ci.yml`

**Files:**
- Modify: `.gitlab-ci.yml` (append frontend test job)

**Interfaces:**
- Consumes: `.gitlab-ci.yml` from Task 1
- Produces: Complete CI/CD pipeline with both backend and frontend jobs

**Steps:**

- [ ] **Step 1: Add frontend test job to `.gitlab-ci.yml`**

Append to the existing file (after the `backend-tests:` job):

```yaml
# Frontend tests using Node.js + Vitest
frontend-tests:
  stage: test
  image: node:18-slim
  before_script:
    - cd frontend
    - npm install
  script:
    - npm test
  artifacts:
    reports:
      junit: frontend/test-results.xml
    when: always
  retry:
    max: 1
    when:
      - runner_system_failure
      - stuck_or_timeout_failure
```

- [ ] **Step 2: Verify Vitest can output JUnit XML**

Check that `frontend/package.json` test script uses vitest. If needed, update the npm test script to generate JUnit output by modifying `package.json`:

```json
"scripts": {
  "dev": "vite",
  "build": "vite build",
  "test": "vitest run --reporter=junit --outputFile=test-results.xml"
}
```

If vitest doesn't have `--reporter` flag, use `--reporter=verbose` instead (JUnit output is optional but helpful).

- [ ] **Step 3: Verify the complete YAML file**

Check that `.gitlab-ci.yml` now has both `stages`, `backend-tests`, and `frontend-tests` jobs. Verify indentation is correct.

Expected: Two jobs under `test` stage, proper YAML structure.

- [ ] **Step 4: Commit frontend test job**

```bash
git add .gitlab-ci.yml frontend/package.json
git commit -m "ci: add frontend vitest job to GitLab CI/CD pipeline"
```

---

## Task 3: Verify and Document CI/CD Setup

**Files:**
- Create: `docs/ci-cd-setup.md` (optional, but recommended)

**Steps:**

- [ ] **Step 1: Create CI/CD documentation**

Create `docs/ci-cd-setup.md` with the following content:

```markdown
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
```

- [ ] **Step 2: Commit documentation**

```bash
git add docs/ci-cd-setup.md
git commit -m "docs: add GitLab CI/CD setup and troubleshooting guide"
```

---

## Task 4: Test the Pipeline in GitLab (If Remote is Configured)

**Files:**
- None (verification only)

**Steps:**

- [ ] **Step 1: Verify `.gitlab-ci.yml` exists in repo**

```bash
git log --oneline -n 5
```

Should show recent commits mentioning "ci: add" messages.

- [ ] **Step 2: Push to GitLab**

If you have a GitLab remote configured:

```bash
git push origin main
```

Then navigate to your GitLab repository → **CI/CD** → **Pipelines** to watch the jobs run.

Expected: Both `backend-tests` and `frontend-tests` jobs appear and run in parallel.

- [ ] **Step 3: Monitor first pipeline run**

Watch for:
- Both jobs starting (green indicators)
- Backend job: pytest runs, tests pass
- Frontend job: npm install completes, vitest runs, tests pass
- Both jobs complete within 5-10 minutes

If any job fails, click on it to see detailed logs and fix the issue.

---

## Verification Checklist

- [ ] `.gitlab-ci.yml` exists at project root
- [ ] File contains both `backend-tests` and `frontend-tests` jobs
- [ ] Both jobs use correct Docker images (python:3.11-slim, node:18-slim)
- [ ] Backend job has PostgreSQL service configured
- [ ] Backend job installs dependencies from requirements-dev.txt
- [ ] Frontend job runs npm install and npm test
- [ ] YAML syntax is valid (no indentation errors)
- [ ] Commits are atomic (one per feature/change)
- [ ] Documentation added to `docs/ci-cd-setup.md`
