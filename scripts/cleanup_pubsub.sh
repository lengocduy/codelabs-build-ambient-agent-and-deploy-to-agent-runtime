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

if [ "$#" -ne 2 ]; then
    echo "Usage: $0 <PROJECT_ID> <REGION>"
    exit 1
fi

PROJECT_ID="$1"
REGION="$2"

echo "Cleaning up resources in project: ${PROJECT_ID} (region: ${REGION})..."

# 0. Delete Cloud Run Service if it exists
if gcloud run services describe expense-manager-dashboard --project="${PROJECT_ID}" --region="${REGION}" >/dev/null 2>&1; then
    echo "Deleting Cloud Run service: expense-manager-dashboard..."
    gcloud run services delete expense-manager-dashboard --project="${PROJECT_ID}" --region="${REGION}" --quiet
else
    echo "Cloud Run service expense-manager-dashboard does not exist."
fi


# 1. Delete push subscription if it exists
if gcloud pubsub subscriptions describe expense-reports-push --project="${PROJECT_ID}" >/dev/null 2>&1; then
    echo "Deleting push subscription: expense-reports-push..."
    gcloud pubsub subscriptions delete expense-reports-push --project="${PROJECT_ID}" --quiet
else
    echo "Push subscription expense-reports-push does not exist."
fi

# 2. Delete topics if they exist
if gcloud pubsub topics describe expense-reports --project="${PROJECT_ID}" >/dev/null 2>&1; then
    echo "Deleting topic: expense-reports..."
    gcloud pubsub topics delete expense-reports --project="${PROJECT_ID}" --quiet
else
    echo "Topic expense-reports does not exist."
fi

if gcloud pubsub topics describe expense-reports-dead-letter --project="${PROJECT_ID}" >/dev/null 2>&1; then
    echo "Deleting dead-letter topic: expense-reports-dead-letter..."
    gcloud pubsub topics delete expense-reports-dead-letter --project="${PROJECT_ID}" --quiet
else
    echo "Dead-letter topic expense-reports-dead-letter does not exist."
fi

# 3. Delete service account if it exists
SA_EMAIL="pubsub-invoker@${PROJECT_ID}.iam.gserviceaccount.com"
if gcloud iam service-accounts describe "${SA_EMAIL}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
    echo "Deleting service account: ${SA_EMAIL}..."
    gcloud iam service-accounts delete "${SA_EMAIL}" --project="${PROJECT_ID}" --quiet
else
    echo "Service account ${SA_EMAIL} does not exist."
fi

echo "Pub/Sub resources cleanup complete."
