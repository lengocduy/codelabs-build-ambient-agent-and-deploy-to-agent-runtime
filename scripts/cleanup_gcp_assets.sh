#!/usr/bin/env bash
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

set -euo pipefail

if [ "$#" -lt 1 ]; then
    echo "Usage: $0 <PROJECT_ID> [REGION]"
    exit 1
fi

PROJECT_ID="$1"
REGION="${2:-us-east1}"

echo "Beginning cleanup of GCS Buckets and Artifact Registry repositories for project: ${PROJECT_ID}..."

# List of buckets to delete
BUCKETS=(
    "${PROJECT_ID}-ambient-expense-agent-logs"
    "${PROJECT_ID}-terraform-state"
    "run-sources-${PROJECT_ID}-${REGION}"
)

for BUCKET in "${BUCKETS[@]}"; do
    if gcloud storage buckets describe "gs://${BUCKET}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
        echo "Deleting bucket and all its contents: gs://${BUCKET}..."
        gcloud storage rm --recursive "gs://${BUCKET}" --project="${PROJECT_ID}"
    else
        echo "Bucket gs://${BUCKET} does not exist."
    fi
done

# List of Artifact Registry repos to delete
# Repository format: name:location
REPOS=(
    "serverless-pipeline-repo:us-central1"
    "cloud-run-source-deploy:us-east1"
    "cloud-run-source-deploy:${REGION}"
)

for REPO_INFO in "${REPOS[@]}"; do
    REPO_NAME="${REPO_INFO%%:*}"
    REPO_LOC="${REPO_INFO##*:}"

    if gcloud artifacts repositories describe "${REPO_NAME}" --location="${REPO_LOC}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
        echo "Deleting Artifact Registry repository: ${REPO_NAME} in location: ${REPO_LOC}..."
        gcloud artifacts repositories delete "${REPO_NAME}" --location="${REPO_LOC}" --project="${PROJECT_ID}" --quiet
    else
        echo "Repository ${REPO_NAME} in ${REPO_LOC} does not exist."
    fi
done

echo "GCP Buckets and Artifact Registry repositories cleanup complete."
