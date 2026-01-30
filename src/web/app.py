"""FastAPI web application for SDLC Agent."""

import asyncio
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="SDLC Agent", description="AI-powered GitHub development automation")

# In-memory job storage (use Redis/DB for production)
jobs: dict[str, "Job"] = {}


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


@dataclass
class Job:
    id: str
    repo: str
    issue_number: int
    status: JobStatus = JobStatus.PENDING
    logs: list[str] = field(default_factory=list)
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: datetime = field(default_factory=datetime.now)
    pr_url: str | None = None


class ProcessRequest(BaseModel):
    repo: str  # e.g., "owner/repo"
    issue_number: int
    github_token: str
    openai_api_key: str | None = None


class JobResponse(BaseModel):
    job_id: str
    status: str
    logs: list[str]
    result: dict[str, Any] | None = None
    error: str | None = None
    pr_url: str | None = None


# HTML Template
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SDLC Agent</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            min-height: 100vh;
            color: #fff;
            padding: 20px;
        }
        .container {
            max-width: 900px;
            margin: 0 auto;
        }
        h1 {
            text-align: center;
            margin-bottom: 30px;
            font-size: 2.5em;
        }
        h1 span { color: #00d9ff; }
        .card {
            background: rgba(255,255,255,0.1);
            border-radius: 16px;
            padding: 30px;
            margin-bottom: 20px;
            backdrop-filter: blur(10px);
        }
        .form-group {
            margin-bottom: 20px;
        }
        label {
            display: block;
            margin-bottom: 8px;
            font-weight: 500;
            color: #aaa;
        }
        input {
            width: 100%;
            padding: 12px 16px;
            border: 1px solid rgba(255,255,255,0.2);
            border-radius: 8px;
            background: rgba(0,0,0,0.3);
            color: #fff;
            font-size: 16px;
        }
        input:focus {
            outline: none;
            border-color: #00d9ff;
        }
        input::placeholder { color: #666; }
        button {
            width: 100%;
            padding: 14px;
            background: linear-gradient(135deg, #00d9ff 0%, #0066ff 100%);
            border: none;
            border-radius: 8px;
            color: #fff;
            font-size: 18px;
            font-weight: 600;
            cursor: pointer;
            transition: transform 0.2s, box-shadow 0.2s;
        }
        button:hover {
            transform: translateY(-2px);
            box-shadow: 0 10px 30px rgba(0, 217, 255, 0.3);
        }
        button:disabled {
            opacity: 0.5;
            cursor: not-allowed;
            transform: none;
        }
        .logs {
            background: #0d1117;
            border-radius: 8px;
            padding: 20px;
            font-family: 'Monaco', 'Menlo', monospace;
            font-size: 13px;
            max-height: 400px;
            overflow-y: auto;
            white-space: pre-wrap;
            word-break: break-all;
        }
        .log-line { margin: 4px 0; }
        .log-info { color: #58a6ff; }
        .log-success { color: #3fb950; }
        .log-error { color: #f85149; }
        .log-warn { color: #d29922; }
        .status {
            display: inline-block;
            padding: 6px 12px;
            border-radius: 20px;
            font-size: 14px;
            font-weight: 500;
        }
        .status-pending { background: #6e7681; }
        .status-running { background: #1f6feb; }
        .status-success { background: #238636; }
        .status-failed { background: #da3633; }
        .result-card {
            margin-top: 20px;
            padding: 20px;
            background: rgba(35, 134, 54, 0.2);
            border: 1px solid #238636;
            border-radius: 8px;
        }
        .result-card.error {
            background: rgba(218, 54, 51, 0.2);
            border-color: #da3633;
        }
        a { color: #58a6ff; }
        .hidden { display: none; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🤖 <span>SDLC</span> Agent</h1>

        <div class="card">
            <form id="processForm">
                <div class="form-group">
                    <label>GitHub Repository</label>
                    <input type="text" id="repo" placeholder="owner/repo" required>
                </div>
                <div class="form-group">
                    <label>Issue Number</label>
                    <input type="number" id="issue" placeholder="123" required>
                </div>
                <div class="form-group">
                    <label>GitHub Token</label>
                    <input type="password" id="token" placeholder="ghp_..." required>
                </div>
                <div class="form-group">
                    <label>OpenAI API Key (optional, uses server default)</label>
                    <input type="password" id="openai" placeholder="sk-...">
                </div>
                <button type="submit" id="submitBtn">🚀 Process Issue</button>
            </form>
        </div>

        <div id="jobSection" class="card hidden">
            <h3>Job Status: <span id="statusBadge" class="status status-pending">pending</span></h3>
            <div class="logs" id="logs"></div>
            <div id="resultSection" class="hidden"></div>
        </div>
    </div>

    <script>
        const form = document.getElementById('processForm');
        const submitBtn = document.getElementById('submitBtn');
        const jobSection = document.getElementById('jobSection');
        const statusBadge = document.getElementById('statusBadge');
        const logsDiv = document.getElementById('logs');
        const resultSection = document.getElementById('resultSection');

        let currentJobId = null;
        let pollInterval = null;

        form.addEventListener('submit', async (e) => {
            e.preventDefault();

            const data = {
                repo: document.getElementById('repo').value,
                issue_number: parseInt(document.getElementById('issue').value),
                github_token: document.getElementById('token').value,
                openai_api_key: document.getElementById('openai').value || null
            };

            submitBtn.disabled = true;
            submitBtn.textContent = '⏳ Starting...';
            jobSection.classList.remove('hidden');
            logsDiv.innerHTML = '';
            resultSection.classList.add('hidden');

            try {
                const res = await fetch('/api/process', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });

                if (!res.ok) {
                    const err = await res.json();
                    throw new Error(err.detail || 'Failed to start job');
                }

                const job = await res.json();
                currentJobId = job.job_id;
                addLog('Job started: ' + currentJobId, 'info');

                // Start polling
                pollInterval = setInterval(pollJob, 2000);

            } catch (err) {
                addLog('Error: ' + err.message, 'error');
                submitBtn.disabled = false;
                submitBtn.textContent = '🚀 Process Issue';
            }
        });

        async function pollJob() {
            if (!currentJobId) return;

            try {
                const res = await fetch('/api/job/' + currentJobId);
                const job = await res.json();

                // Update status
                statusBadge.textContent = job.status;
                statusBadge.className = 'status status-' + job.status;

                // Update logs
                logsDiv.innerHTML = job.logs.map(log => {
                    let cls = 'log-line';
                    if (log.includes('✅') || log.includes('success')) cls += ' log-success';
                    else if (log.includes('❌') || log.includes('error') || log.includes('Error')) cls += ' log-error';
                    else if (log.includes('⚠️') || log.includes('warning')) cls += ' log-warn';
                    else cls += ' log-info';
                    return `<div class="${cls}">${escapeHtml(log)}</div>`;
                }).join('');
                logsDiv.scrollTop = logsDiv.scrollHeight;

                // Check if done
                if (job.status === 'success' || job.status === 'failed') {
                    clearInterval(pollInterval);
                    submitBtn.disabled = false;
                    submitBtn.textContent = '🚀 Process Issue';

                    resultSection.classList.remove('hidden');
                    if (job.status === 'success') {
                        resultSection.className = 'result-card';
                        let html = '<h4>✅ Success!</h4>';
                        if (job.pr_url) {
                            html += `<p>Pull Request: <a href="${job.pr_url}" target="_blank">${job.pr_url}</a></p>`;
                        }
                        resultSection.innerHTML = html;
                    } else {
                        resultSection.className = 'result-card error';
                        resultSection.innerHTML = `<h4>❌ Failed</h4><p>${escapeHtml(job.error || 'Unknown error')}</p>`;
                    }
                }

            } catch (err) {
                addLog('Poll error: ' + err.message, 'error');
            }
        }

        function addLog(msg, type = 'info') {
            const div = document.createElement('div');
            div.className = 'log-line log-' + type;
            div.textContent = new Date().toLocaleTimeString() + ' ' + msg;
            logsDiv.appendChild(div);
            logsDiv.scrollTop = logsDiv.scrollHeight;
        }

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
    </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def home():
    """Serve the web interface."""
    return HTML_TEMPLATE


@app.post("/api/process", response_model=JobResponse)
async def process_issue(request: ProcessRequest, background_tasks: BackgroundTasks):
    """Start processing a GitHub issue."""
    job_id = str(uuid.uuid4())[:8]

    job = Job(
        id=job_id,
        repo=request.repo,
        issue_number=request.issue_number,
    )
    jobs[job_id] = job

    # Run in background
    background_tasks.add_task(
        run_agent_job,
        job,
        request.github_token,
        request.openai_api_key,
    )

    return JobResponse(
        job_id=job.id,
        status=job.status.value,
        logs=job.logs,
    )


@app.get("/api/job/{job_id}", response_model=JobResponse)
async def get_job(job_id: str):
    """Get job status and logs."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    job = jobs[job_id]
    return JobResponse(
        job_id=job.id,
        status=job.status.value,
        logs=job.logs,
        result=job.result,
        error=job.error,
        pr_url=job.pr_url,
    )


async def run_agent_job(job: Job, github_token: str, openai_api_key: str | None):
    """Run the SDLC agent in background."""
    import tempfile

    job.status = JobStatus.RUNNING
    job.logs.append(f"🚀 Starting job for {job.repo} issue #{job.issue_number}")

    try:
        # Set environment variables
        os.environ["GITHUB_TOKEN"] = github_token
        os.environ["GITHUB_REPOSITORY"] = job.repo
        if openai_api_key:
            os.environ["OPENAI_API_KEY"] = openai_api_key

        job.logs.append("📦 Cloning repository...")

        # Clone repo to temp directory
        with tempfile.TemporaryDirectory() as tmpdir:
            clone_url = f"https://x-access-token:{github_token}@github.com/{job.repo}.git"

            process = await asyncio.create_subprocess_exec(
                "git", "clone", clone_url, tmpdir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await process.communicate()

            if process.returncode != 0:
                raise Exception(f"Failed to clone: {stderr.decode()}")

            job.logs.append(f"✅ Cloned to {tmpdir}")

            # Set workspace
            os.environ["WORKSPACE_DIR"] = tmpdir

            # Import and run agent
            job.logs.append("🤖 Starting agent...")

            from src.agents.code_agent import CodeAgent
            from src.core.config import get_settings
            from src.github.client import GitHubClient

            settings = get_settings()
            github_client = GitHubClient(
                token=settings.github_token,
                repository=settings.github_repository,
            )

            agent = CodeAgent(settings, github_client)

            # Capture logs
            def log_callback(msg: str):
                job.logs.append(msg)

            # Process issue
            job.logs.append(f"📋 Processing issue #{job.issue_number}...")
            result = agent.process_issue(job.issue_number, max_iterations=15)

            if result.get("success"):
                job.status = JobStatus.SUCCESS
                job.pr_url = result.get("pr_url")
                job.result = result
                job.logs.append(f"✅ Success! PR: {job.pr_url}")
            else:
                job.status = JobStatus.FAILED
                job.error = result.get("summary", "Unknown error")
                job.logs.append(f"❌ Failed: {job.error}")

    except Exception as e:
        job.status = JobStatus.FAILED
        job.error = str(e)
        job.logs.append(f"❌ Error: {e}")


def start_server(host: str = "0.0.0.0", port: int = 8000):
    """Start the web server."""
    import uvicorn
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    start_server()
