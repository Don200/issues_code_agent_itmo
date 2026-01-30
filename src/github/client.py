"""GitHub API client wrapper."""

from dataclasses import dataclass
from typing import Any

import structlog
from github import Auth, Github, GithubException
from github.GithubObject import NotSet
from github.Issue import Issue
from github.PullRequest import PullRequest
from github.Repository import Repository

from src.core.exceptions import GitHubAPIError

logger = structlog.get_logger()


@dataclass
class CICheckResult:
    """Result of a CI check."""

    name: str
    status: str  # queued, in_progress, completed
    conclusion: str | None  # success, failure, neutral, cancelled, skipped, timed_out
    url: str | None = None
    output: dict[str, Any] | None = None


class GitHubClient:
    """Client for GitHub API operations."""

    def __init__(self, token: str, repository: str) -> None:
        """
        Initialize GitHub client.

        Args:
            token: GitHub API token
            repository: Repository in format owner/repo
        """
        self._token = token
        self._repository = repository
        self._github = Github(auth=Auth.Token(token))
        self._repo: Repository | None = None
        self._log = logger.bind(component="github_client", repository=repository)

    @property
    def repo(self) -> Repository:
        """Get repository object, lazily loaded."""
        if self._repo is None:
            try:
                self._repo = self._github.get_repo(self._repository)
                self._log.debug("repository_loaded", repo=self._repository)
            except GithubException as e:
                raise GitHubAPIError(
                    f"Failed to access repository: {self._repository}",
                    status_code=e.status,
                    details={"error": str(e)},
                ) from e
        return self._repo

    def get_issue(self, issue_number: int) -> Issue:
        """
        Get issue by number.

        Args:
            issue_number: Issue number

        Returns:
            GitHub Issue object
        """
        try:
            issue = self.repo.get_issue(issue_number)
            self._log.debug("issue_fetched", issue_number=issue_number)
            return issue
        except GithubException as e:
            raise GitHubAPIError(
                f"Failed to get issue #{issue_number}",
                status_code=e.status,
                details={"issue_number": issue_number, "error": str(e)},
            ) from e

    def get_pull_request(self, pr_number: int) -> PullRequest:
        """
        Get pull request by number.

        Args:
            pr_number: PR number

        Returns:
            GitHub PullRequest object
        """
        try:
            pr = self.repo.get_pull(pr_number)
            self._log.debug("pr_fetched", pr_number=pr_number)
            return pr
        except GithubException as e:
            raise GitHubAPIError(
                f"Failed to get PR #{pr_number}",
                status_code=e.status,
                details={"pr_number": pr_number, "error": str(e)},
            ) from e

    def create_pull_request(
        self,
        title: str,
        body: str,
        head: str,
        base: str = "main",
    ) -> PullRequest:
        """
        Create a new pull request.

        Args:
            title: PR title
            body: PR description
            head: Source branch
            base: Target branch

        Returns:
            Created PullRequest object
        """
        try:
            pr = self.repo.create_pull(
                title=title,
                body=body,
                head=head,
                base=base,
            )
            self._log.info("pr_created", pr_number=pr.number, title=title)
            return pr
        except GithubException as e:
            raise GitHubAPIError(
                "Failed to create pull request",
                status_code=e.status,
                details={"title": title, "head": head, "base": base, "error": str(e)},
            ) from e

    def add_pr_comment(self, pr_number: int, body: str) -> None:
        """
        Add a comment to a pull request.

        Args:
            pr_number: PR number
            body: Comment body
        """
        try:
            pr = self.get_pull_request(pr_number)
            pr.create_issue_comment(body)
            self._log.debug("pr_comment_added", pr_number=pr_number)
        except GithubException as e:
            raise GitHubAPIError(
                f"Failed to add comment to PR #{pr_number}",
                status_code=e.status,
                details={"pr_number": pr_number, "error": str(e)},
            ) from e

    def add_pr_review(
        self,
        pr_number: int,
        body: str,
        event: str = "COMMENT",
        comments: list[dict[str, Any]] | None = None,
    ) -> None:
        """
        Add a review to a pull request.

        Args:
            pr_number: PR number
            body: Review body
            event: Review event (APPROVE, REQUEST_CHANGES, COMMENT)
            comments: List of inline review comments
        """
        try:
            pr = self.get_pull_request(pr_number)
            pr.create_review(
                body=body,
                event=event,
                comments=comments or [],
            )
            self._log.info("pr_review_added", pr_number=pr_number, review_event=event)
        except GithubException as e:
            # GitHub doesn't allow APPROVE/REQUEST_CHANGES on own PRs
            # Fall back to regular comment
            if e.status == 422 and event in ("APPROVE", "REQUEST_CHANGES"):
                self._log.warning(
                    "Cannot submit formal review on own PR, posting as comment",
                    pr_number=pr_number,
                    review_event=event,
                )
                self.add_pr_comment(pr_number, f"**[{event}]**\n\n{body}")
            else:
                raise GitHubAPIError(
                    f"Failed to add review to PR #{pr_number}",
                    status_code=e.status,
                    details={"pr_number": pr_number, "event": event, "error": str(e)},
                ) from e

    def get_pr_diff(self, pr_number: int) -> str:
        """
        Get the diff of a pull request.

        Args:
            pr_number: PR number

        Returns:
            Diff as string
        """
        try:
            pr = self.get_pull_request(pr_number)
            # Get files changed in PR
            files = pr.get_files()
            diff_parts = []
            for file in files:
                diff_parts.append(f"--- {file.filename}")
                if file.patch:
                    diff_parts.append(file.patch)
            return "\n".join(diff_parts)
        except GithubException as e:
            raise GitHubAPIError(
                f"Failed to get diff for PR #{pr_number}",
                status_code=e.status,
                details={"pr_number": pr_number, "error": str(e)},
            ) from e

    def get_pr_files(self, pr_number: int) -> list[dict[str, Any]]:
        """
        Get list of files changed in a pull request.

        Args:
            pr_number: PR number

        Returns:
            List of file info dicts
        """
        try:
            pr = self.get_pull_request(pr_number)
            files = []
            for file in pr.get_files():
                files.append({
                    "filename": file.filename,
                    "status": file.status,
                    "additions": file.additions,
                    "deletions": file.deletions,
                    "changes": file.changes,
                    "patch": file.patch,
                })
            return files
        except GithubException as e:
            raise GitHubAPIError(
                f"Failed to get files for PR #{pr_number}",
                status_code=e.status,
                details={"pr_number": pr_number, "error": str(e)},
            ) from e

    def get_ci_status(self, pr_number: int) -> list[CICheckResult]:
        """
        Get CI check results for a pull request.

        Args:
            pr_number: PR number

        Returns:
            List of CI check results
        """
        try:
            pr = self.get_pull_request(pr_number)
            commit = self.repo.get_commit(pr.head.sha)
            check_runs = commit.get_check_runs()

            results = []
            for check in check_runs:
                output_data = None

                # Handle check.output (can be NotSet or actual data)
                if check.output and check.output is not NotSet:
                    title = check.output.title if check.output.title is not NotSet else None
                    summary = check.output.summary if check.output.summary is not NotSet else None
                    text = None
                    if hasattr(check.output, 'text') and check.output.text is not NotSet:
                        text = check.output.text

                    if title or summary or text:
                        output_data = {}
                        if title:
                            output_data["title"] = title
                        if summary:
                            output_data["summary"] = summary
                        if text:
                            output_data["text"] = text[:2000]

                # Fetch annotations separately (PyGithub requires this)
                try:
                    annotations = list(check.get_annotations()[:10])
                    if annotations:
                        if output_data is None:
                            output_data = {}
                        output_data["annotations"] = [
                            {
                                "path": a.path,
                                "line": a.start_line,
                                "message": a.message,
                                "level": a.annotation_level,
                            }
                            for a in annotations
                        ]
                except Exception:
                    pass  # Annotations not available

                # Add URL to output for failed checks
                if check.conclusion != "success" and check.html_url:
                    if output_data is None:
                        output_data = {}
                    output_data["url"] = check.html_url

                    logger.debug(
                        "CI check failed",
                        name=check.name,
                        conclusion=check.conclusion,
                        url=check.html_url,
                        has_summary=output_data.get("summary") is not None,
                    )

                results.append(CICheckResult(
                    name=check.name,
                    status=check.status,
                    conclusion=check.conclusion,
                    url=check.html_url,
                    output=output_data,
                ))
            return results
        except GithubException as e:
            raise GitHubAPIError(
                f"Failed to get CI status for PR #{pr_number}",
                status_code=e.status,
                details={"pr_number": pr_number, "error": str(e)},
            ) from e

    def get_workflow_run_logs(self, pr_number: int) -> str | None:
        """
        Get workflow run logs for a PR's failed checks.

        Args:
            pr_number: PR number

        Returns:
            Log content or None if not available
        """
        import io
        import zipfile

        import requests

        try:
            pr = self.get_pull_request(pr_number)
            commit = self.repo.get_commit(pr.head.sha)

            # Find failed workflow runs
            for run in self.repo.get_workflow_runs(head_sha=pr.head.sha):
                if run.conclusion == "failure":
                    # Get logs URL
                    logs_url = run.logs_url

                    # Download logs (requires auth)
                    headers = {"Authorization": f"Bearer {self._token}"}
                    response = requests.get(logs_url, headers=headers, timeout=30)

                    if response.status_code == 200:
                        # Logs come as a zip file
                        zip_file = zipfile.ZipFile(io.BytesIO(response.content))

                        # Extract and combine relevant log files
                        logs = []
                        for name in zip_file.namelist():
                            if name.endswith(".txt"):
                                content = zip_file.read(name).decode("utf-8", errors="ignore")
                                # Look for error sections
                                if "error" in content.lower() or "failed" in content.lower():
                                    # Get last 200 lines which usually contain the error
                                    lines = content.strip().split("\n")
                                    logs.append(f"=== {name} ===\n" + "\n".join(lines[-200:]))

                        if logs:
                            return "\n\n".join(logs)[:5000]  # Limit total size

            return None
        except Exception as e:
            logger.warning("Failed to get workflow logs", error=str(e))
            return None

    def get_file_content(self, path: str, ref: str = "main") -> str | None:
        """
        Get content of a file from repository.

        Args:
            path: File path in repository
            ref: Git reference (branch, tag, commit)

        Returns:
            File content or None if not found
        """
        try:
            content = self.repo.get_contents(path, ref=ref)
            if isinstance(content, list):
                return None  # It's a directory
            return content.decoded_content.decode("utf-8")
        except GithubException as e:
            if e.status == 404:
                return None
            raise GitHubAPIError(
                f"Failed to get file content: {path}",
                status_code=e.status,
                details={"path": path, "ref": ref, "error": str(e)},
            ) from e

    def get_repository_structure(self, path: str = "", ref: str = "main") -> list[dict[str, Any]]:
        """
        Get repository file structure.

        Args:
            path: Starting path
            ref: Git reference

        Returns:
            List of file/directory info
        """
        try:
            contents = self.repo.get_contents(path, ref=ref)
            if not isinstance(contents, list):
                contents = [contents]

            structure = []
            for item in contents:
                structure.append({
                    "name": item.name,
                    "path": item.path,
                    "type": item.type,  # "file" or "dir"
                    "size": item.size,
                })
            return structure
        except GithubException as e:
            raise GitHubAPIError(
                f"Failed to get repository structure: {path}",
                status_code=e.status,
                details={"path": path, "ref": ref, "error": str(e)},
            ) from e

    def update_issue_labels(self, issue_number: int, labels: list[str]) -> None:
        """
        Update labels on an issue.

        Args:
            issue_number: Issue number
            labels: List of label names
        """
        try:
            issue = self.get_issue(issue_number)
            issue.set_labels(*labels)
            self._log.debug("issue_labels_updated", issue_number=issue_number, labels=labels)
        except GithubException as e:
            raise GitHubAPIError(
                f"Failed to update labels on issue #{issue_number}",
                status_code=e.status,
                details={"issue_number": issue_number, "labels": labels, "error": str(e)},
            ) from e

    def add_issue_comment(self, issue_number: int, body: str) -> None:
        """
        Add a comment to an issue.

        Args:
            issue_number: Issue number
            body: Comment body
        """
        try:
            issue = self.get_issue(issue_number)
            issue.create_comment(body)
            self._log.debug("issue_comment_added", issue_number=issue_number)
        except GithubException as e:
            raise GitHubAPIError(
                f"Failed to add comment to issue #{issue_number}",
                status_code=e.status,
                details={"issue_number": issue_number, "error": str(e)},
            ) from e

    def close(self) -> None:
        """Close the GitHub client connection."""
        self._github.close()
        self._log.debug("github_client_closed")
