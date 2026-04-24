#!/bin/bash
# No-op for devops_tl tasks. The test fixtures start postgres + redis on
# demand; the grader invokes pytest directly. This file exists only so
# the launchpad harness's run_servers.sh contract isn't broken.
exit 0
