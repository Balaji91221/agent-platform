"""Jenkins CI: the three jobs that provision, deploy and tear down an agent."""

from app.cicd.jenkins import JobRun, agent_slug, host_entry, jobs_for_agent, trigger

__all__ = ["JobRun", "agent_slug", "host_entry", "jobs_for_agent", "trigger"]
