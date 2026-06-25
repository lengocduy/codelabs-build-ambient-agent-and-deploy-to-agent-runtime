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

if [ "$#" -ne 3 ]; then
    echo "Usage: $0 <PROJECT_ID> <REGION> <PROJECT_NUMBER>"
    exit 1
fi

PROJECT_ID="$1"
REGION="$2"
PROJECT_NUMBER="$3"

if [ ! -f "deployment_metadata.json" ]; then
    echo "Error: deployment_metadata.json not found in the current directory."
    exit 1
fi

REASONING_ENGINE_ID=$(jq -r '.remote_agent_runtime_id' deployment_metadata.json)
if [ -z "${REASONING_ENGINE_ID}" ] || [ "${REASONING_ENGINE_ID}" = "null" ]; then
    echo "Error: Could not resolve remote_agent_runtime_id from deployment_metadata.json."
    exit 1
fi

echo "Connecting Pub/Sub push subscription to Agent Runtime ID: ${REASONING_ENGINE_ID}"

# 1. Create topics if they don't exist
gcloud pubsub topics create expense-reports-dead-letter --project="${PROJECT_ID}" || true
gcloud pubsub topics create expense-reports --project="${PROJECT_ID}" || true

# 2. Create pubsub-invoker service account
gcloud iam service-accounts create pubsub-invoker \
  --description="Service account for Pub/Sub push authentication" \
  --display-name="Pub/Sub Invoker Service Account" \
  --project="${PROJECT_ID}" || true

# 3. Grant Vertex AI User role to invoker service account
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:pubsub-invoker@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/aiplatform.user"

# 4. Grant publisher permissions to Pub/Sub agent on the dead-letter topic
gcloud pubsub topics add-iam-policy-binding expense-reports-dead-letter \
  --member="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-pubsub.iam.gserviceaccount.com" \
  --role="roles/pubsub.publisher" \
  --project="${PROJECT_ID}"

# 5. Create or update push subscription with the reasoning engine endpoint
PUSH_ENDPOINT="https://${REGION}-aiplatform.googleapis.com/v1/${REASONING_ENGINE_ID}:streamQuery"

if gcloud pubsub subscriptions describe expense-reports-push --project="${PROJECT_ID}" >/dev/null 2>&1; then
  echo "Push subscription already exists. Updating endpoint..."
  gcloud pubsub subscriptions update expense-reports-push \
    --push-endpoint="${PUSH_ENDPOINT}" \
    --push-auth-token-audience="${PUSH_ENDPOINT}" \
    --project="${PROJECT_ID}"
else
  echo "Push subscription does not exist. Creating..."
  gcloud pubsub subscriptions create expense-reports-push \
    --topic=expense-reports \
    --push-endpoint="${PUSH_ENDPOINT}" \
    --push-no-wrapper \
    --push-auth-service-account="pubsub-invoker@${PROJECT_ID}.iam.gserviceaccount.com" \
    --push-auth-token-audience="${PUSH_ENDPOINT}" \
    --ack-deadline=600 \
    --dead-letter-topic=expense-reports-dead-letter \
    --max-delivery-attempts=5 \
    --project="${PROJECT_ID}"
fi
