#!/bin/sh
set -eu
exec "${AIQA_WORKER_PYTHON:-python3}" -B -m aiqa.hosted.worker
