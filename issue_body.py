"""
Shared issue/comment body builders for GitLab and GitHub.
"""
import os


def build_issue_body(environment: str, test_name: str, details: dict) -> str:
    ctx = details.get("context", {})
    traceback_text = details.get("longrepr", "No details available")

    sections = [f"## Smoke test failure: `{test_name}`"]
    sections.append(f"**Environment:** {environment.upper()}")

    if ctx:
        sections.append("### Triage context")
        for k, v in ctx.items():
            sections.append(f"- **{k}:** `{v}`")

    sections.append("### Traceback")
    sections.append(f"```\n{traceback_text}\n```")

    pipeline_url = os.getenv("CI_PIPELINE_URL")
    job_url = os.getenv("CI_JOB_URL")
    if pipeline_url:
        sections.append(f"**Pipeline:** {pipeline_url}")
    if job_url:
        sections.append(f"**Job:** {job_url}")

    return "\n\n".join(sections)


def build_comment_body(environment: str, details: dict) -> str:
    ctx = details.get("context", {})
    traceback_text = details.get("longrepr", "No details available")

    sections = [f"### Still failing — {environment.upper()}"]

    if ctx:
        ctx_str = " | ".join(f"**{k}:** `{v}`" for k, v in ctx.items())
        sections.append(ctx_str)

    sections.append(f"```\n{traceback_text}\n```")

    pipeline_url = os.getenv("CI_PIPELINE_URL")
    if pipeline_url:
        sections.append(f"**Pipeline:** {pipeline_url}")

    return "\n\n".join(sections)
