# FILE: yascheduler/aiida_plugin.py
# VERSION: 1.6.0
#
# START_MODULE_CONTRACT
#   PURPOSE: AiiDA scheduler plugin entry point for integrating with AiiDA workflows.
#   SCOPE: AiiDA Scheduler subclass implementation.
#   DEPENDS: none
#   LINKS: M-CLIENT
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   YaschedJobResource - Resource class for yascheduler jobs in AiiDA.
#   YaScheduler - AiiDA Scheduler subclass for the yascheduler engine.
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.6.0 - Initial GRACE-lite markup.
# END_CHANGE_SUMMARY
#

"""
Aiida plugin for yascheduler,
with respect to the supported yascheduler engines
"""

from typing import NoReturn

import aiida.schedulers
from aiida.common.escaping import escape_for_bash
from aiida.common.exceptions import FeatureNotAvailable
from aiida.orm import load_node
from aiida.schedulers.datastructures import (
    JobInfo,
    JobState,
    JobTemplate,
    NodeNumberJobResource,
)
from aiida.schedulers.scheduler import SchedulerError

_MAP_STATUS_YASCHEDULER = {
    "TO_DO": JobState.QUEUED,
    "RUNNING": JobState.RUNNING,
    "DONE": JobState.DONE,
}
_CMD_PREFIX = ""  # NB under virtualenv, this should refer to virtualenv's /bin/


class YaschedJobResource(NodeNumberJobResource):
    # START_CONTRACT: __init__
    #   PURPOSE: Initialize YaschedJobResource with keyword arguments for AiiDA job resource
    #   INPUTS: { kwargs: dict - keyword arguments passed to parent NodeNumberJobResource }
    #   OUTPUTS: { None - no return value }
    #   SIDE_EFFECTS: Calls parent constructor with provided arguments
    #   LINKS: M-AIIDA
    # END_CONTRACT: __init__
    def __init__(self, *_, **kwargs) -> None:  # noqa: ANN002, ANN003
        super().__init__(**kwargs)


class YaScheduler(aiida.schedulers.Scheduler):
    """
    Support for the YaScheduler designed specifically for MPDS
    """

    _logger = aiida.schedulers.Scheduler._logger.getChild("yascheduler")

    # Query only by list of jobs and not by user
    _features = {
        "can_query_by_user": False,
    }

    # The class to be used for the job resource.
    _job_resource_class = YaschedJobResource

    # START_CONTRACT: submit_job
    #   PURPOSE: Submit a job script to yascheduler via transport
    #   INPUTS: { working_directory: str - remote working directory for the job } | { filename: str - job script filename }
    #   OUTPUTS: { str - job ID parsed from submit command output }
    #   SIDE_EFFECTS: Changes remote working directory via transport, executes submit command
    #   LINKS: M-AIIDA
    # END_CONTRACT: submit_job
    def submit_job(self, working_directory: str, filename: str) -> str:
        """
        Submit a job script to yascheduler.

        AiiDA 2.7 makes this public method abstract on the base Scheduler.
        Older AiiDA versions provided the same behavior through submit_from_script.
        """
        self.transport.chdir(working_directory)
        result = self.transport.exec_command_wait(
            self._get_submit_command(escape_for_bash(filename))
        )
        return self._parse_submit_output(*result)

    # START_CONTRACT: get_jobs
    #   PURPOSE: Return list of currently active jobs from yascheduler
    #   INPUTS: { jobs: Optional - list of job IDs to query } | { user: Optional - not supported, raises FeatureNotAvailable } | { as_dict: bool - return as dict keyed by job_id }
    #   OUTPUTS: { list[JobInfo] - list of job info objects } | { dict - dict of job info keyed by job_id if as_dict=True }
    #   SIDE_EFFECTS: Executes remote command via transport
    #   LINKS: M-AIIDA
    # END_CONTRACT: get_jobs
    def get_jobs(
        self,
        jobs: str | list[str] | None = None,
        user: str | None = None,
        as_dict: bool = False,
    ) -> list[JobInfo] | dict[str, JobInfo]:
        """
        Return the list of currently active jobs.

        AiiDA 2.7 makes this public method abstract on the base Scheduler.
        """
        with self.transport:
            retval, stdout, stderr = self.transport.exec_command_wait(
                self._get_joblist_command(jobs=jobs, user=user)
            )

        joblist = self._parse_joblist_output(retval, stdout, stderr)
        if as_dict:
            jobdict = {job.job_id: job for job in joblist}
            if None in jobdict:
                raise SchedulerError("Found at least one job without jobid")
            return jobdict

        return joblist

    # START_CONTRACT: kill_job
    #   PURPOSE: Report that job cancellation is not supported by yascheduler
    #   INPUTS: { jobid: str - ID of the job to kill }
    #   OUTPUTS: { bool - always returns False (kill not supported) }
    #   SIDE_EFFECTS: Logs a warning about unsupported job cancellation
    #   LINKS: M-AIIDA
    # END_CONTRACT: kill_job
    def kill_job(self, jobid: str) -> bool:
        """
        Report that job cancellation is not supported by yascheduler.

        The CLI currently exposes status and submit commands, but no task
        cancellation command. Returning False lets AiiDA handle this as an
        unsuccessful kill without pretending the remote task was stopped.
        """
        self.logger.warning(
            f"Job cancellation is not supported by yascheduler: {jobid}"
        )
        return False

    # START_CONTRACT: _get_joblist_command
    #   PURPOSE: Build the shell command to query job status from yascheduler
    #   INPUTS: { jobs: Optional[list[str]] - specific job IDs to query, user: Optional[str] - not supported }
    #   OUTPUTS: { str - the shell command string }
    #   SIDE_EFFECTS: None
    #   LINKS: M-AIIDA
    # END_CONTRACT: _get_joblist_command
    def _get_joblist_command(
        self, jobs: str | list[str] | None = None, user: str | None = None
    ) -> str:
        """
        The command to report full information on existing jobs.
        """

        if user:
            raise FeatureNotAvailable("Cannot query by user in Yascheduler")
        command = [f"{_CMD_PREFIX}yastatus"]
        # make list from job ids (taken from slurm scheduler)
        if jobs:
            joblist = []
            if isinstance(jobs, str):
                joblist.append(jobs)
            else:
                if not isinstance(jobs, (tuple, list)):
                    raise TypeError(
                        "If provided, the 'jobs' variable must be a string or a list of strings"
                    )
                joblist = jobs
            command.append("--jobs {}".format(" ".join(joblist)))
        return " ".join(command)

    # START_CONTRACT: _get_detailed_jobinfo_command
    #   PURPOSE: Build shell command to get detailed info for a specific job
    #   INPUTS: { jobid: str - the job ID }
    #   OUTPUTS: { str - the shell command string }
    #   SIDE_EFFECTS: None
    #   LINKS: M-AIIDA
    # END_CONTRACT: _get_detailed_jobinfo_command
    def _get_detailed_jobinfo_command(self, jobid: str) -> str:
        """
        Return the command to run to get the detailed information on a job,
        even after the job has finished.
        """
        return f"{_CMD_PREFIX}yastatus --jobs {jobid}"

    # START_CONTRACT: _get_detailed_job_info_command
    #   PURPOSE: Delegate to _get_detailed_jobinfo_command (AiiDA expected method name)
    #   INPUTS: { job_id: str - the job ID }
    #   OUTPUTS: { str - the shell command string }
    #   SIDE_EFFECTS: None
    #   LINKS: M-AIIDA
    # END_CONTRACT: _get_detailed_job_info_command
    def _get_detailed_job_info_command(self, job_id: str) -> str:
        """
        Return the command to run to get detailed information on a job.

        This is the method name expected by AiiDA. Keep the older misspelled
        variant above as an alias for any external callers.
        """
        return self._get_detailed_jobinfo_command(job_id)

    # START_CONTRACT: _get_submit_script_header
    #   PURPOSE: Generate the submit script header with ENGINE and LABEL variables
    #   INPUTS: { job_tmpl: JobTemplate - AiiDA job template object }
    #   OUTPUTS: { str - the header lines (ENGINE, optional PARENT, LABEL) }
    #   SIDE_EFFECTS: Loads AiiDA node from DB via load_node()
    #   LINKS: M-AIIDA
    # END_CONTRACT: _get_submit_script_header
    def _get_submit_script_header(self, job_tmpl: JobTemplate) -> str:
        """
        Return the submit script header, using the parameters from the
        job_tmpl.
        """
        assert job_tmpl.job_name
        # There is no other way to get the code label and the WF uuid except this (TODO?)
        pk = int(job_tmpl.job_name.split("-")[1])
        aiida_node = load_node(pk)

        # We map the lowercase code labels onto yascheduler engines,
        # so that the required input file(s) can be deduced
        lines = [f"ENGINE={aiida_node.inputs.code.label.lower()}"]

        try:
            lines.append(f"PARENT={aiida_node.caller.uuid}")
        except AttributeError:
            pass

        lines.append(f"LABEL={job_tmpl.job_name}")
        return "\n".join(lines)

    # START_CONTRACT: _get_submit_command
    #   PURPOSE: Build the shell command to submit a script via yasubmit
    #   INPUTS: { submit_script: str - the script filename to submit }
    #   OUTPUTS: { str - the shell command string }
    #   SIDE_EFFECTS: None
    #   LINKS: M-AIIDA
    # END_CONTRACT: _get_submit_command
    def _get_submit_command(self, submit_script: str) -> str:
        """
        Return the string to execute to submit a given script.
        """
        return f"{_CMD_PREFIX}yasubmit {submit_script}"

    # START_CONTRACT: _parse_submit_output
    #   PURPOSE: Parse the output of the yasubmit command to extract task ID
    #   INPUTS: { retval: int - return code, stdout: str - stdout text, stderr: str - stderr text }
    #   OUTPUTS: { str - the task ID string }
    #   SIDE_EFFECTS: Logs warnings/errors on stderr or invalid output
    #   LINKS: M-AIIDA
    # END_CONTRACT: _parse_submit_output
    def _parse_submit_output(self, retval: int, stdout: str, stderr: str) -> str:
        """
        Parse the output of the submit command, as returned by executing the
        command returned by _get_submit_command command.
        """
        if stderr.strip():
            self.logger.warning(f"Stderr when submitting: {stderr.strip()}")

        output = stdout.strip()

        try:
            int(output)
        except ValueError:
            self.logger.error("Submitting failed, no task id received")

        return output

    # START_CONTRACT: _parse_joblist_output
    #   PURPOSE: Parse yastatus output into JobInfo objects
    #   INPUTS: { retval: int - return code, stdout: str - stdout with job lines, stderr: str - stderr text }
    #   OUTPUTS: { list[JobInfo] - parsed job info objects }
    #   SIDE_EFFECTS: Logs warnings on stderr
    #   LINKS: M-AIIDA
    # END_CONTRACT: _parse_joblist_output
    def _parse_joblist_output(
        self, retval: int, stdout: str, stderr: str
    ) -> list[JobInfo]:
        """
        Parse the queue output string, as returned by executing the
        command returned by _get_joblist_command command,
        that is here implemented as a list of lines, one for each
        job, with _field_separator as separator. The order is described
        in the _get_joblist_command function.
        Return a list of JobInfo objects, one of each job,
        each relevant parameters implemented.
        """
        if stderr.strip():
            self.logger.warning(f"Stderr when parsing joblist: {stderr.strip()}")
        job_list = [job.split() for job in stdout.split("\n") if job]
        job_infos = []
        for job_id, status in job_list:
            job = JobInfo()
            job.job_id = job_id
            job.job_state = _MAP_STATUS_YASCHEDULER[status]
            job_infos.append(job)
        return job_infos

    # START_CONTRACT: _get_kill_command
    #   PURPOSE: Report that job kill is not supported (raises FeatureNotAvailable)
    #   INPUTS: { jobid: str - the job ID to kill }
    #   OUTPUTS: { None - raises FeatureNotAvailable }
    #   SIDE_EFFECTS: Raises FeatureNotAvailable exception
    #   LINKS: M-AIIDA
    # END_CONTRACT: _get_kill_command
    def _get_kill_command(self, jobid: str) -> NoReturn:
        """
        Return the command to kill the job with specified jobid.
        """
        raise FeatureNotAvailable("Job cancellation is not supported by Yascheduler")

    # START_CONTRACT: _parse_kill_output
    #   PURPOSE: Return False indicating kill was not performed
    #   INPUTS: { retval: int - return code, stdout: str - stdout text, stderr: str - stderr text }
    #   OUTPUTS: { bool - always returns False }
    #   SIDE_EFFECTS: None
    #   LINKS: M-AIIDA
    # END_CONTRACT: _parse_kill_output
    def _parse_kill_output(self, retval: int, stdout: str, stderr: str) -> bool:
        """
        Parse the output of the kill command.
        """
        return False
