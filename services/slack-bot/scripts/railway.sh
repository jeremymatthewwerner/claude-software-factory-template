#!/bin/bash
# Railway CLI wrapper using GraphQL API
# Usage: ./railway.sh <command> [args]
#
# Commands:
#   status          - Get current deployment status
#   logs [limit]    - Get deployment logs (default: 50 lines)
#   deployments [n] - List recent deployments (default: 5)
#   redeploy        - Trigger a redeploy
#   rollback <id>   - Rollback to a specific deployment ID
#   info            - Get service information

set -e

RAILWAY_API="https://backboard.railway.com/graphql/v2"

# Check required environment variables
if [ -z "$RAILWAY_TOKEN" ]; then
  echo "Error: RAILWAY_TOKEN environment variable not set"
  exit 1
fi

if [ -z "$RAILWAY_SERVICE_ID" ]; then
  echo "Error: RAILWAY_SERVICE_ID environment variable not set"
  exit 1
fi

if [ -z "$RAILWAY_ENVIRONMENT_ID" ]; then
  echo "Error: RAILWAY_ENVIRONMENT_ID environment variable not set"
  exit 1
fi

# Helper function to execute GraphQL queries
railway_query() {
  local query="$1"
  local variables="${2:-{}}"

  curl -s -X POST "$RAILWAY_API" \
    -H "Authorization: Bearer $RAILWAY_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"query\": \"$query\", \"variables\": $variables}"
}

# Get current deployment status
cmd_status() {
  local query="query { deployments(first: 1, input: { serviceId: \\\"$RAILWAY_SERVICE_ID\\\", environmentId: \\\"$RAILWAY_ENVIRONMENT_ID\\\" }) { edges { node { id status createdAt meta { commitHash commitMessage branch } } } } }"

  local result=$(railway_query "$query")

  # Parse with jq if available, otherwise show raw
  if command -v jq &> /dev/null; then
    echo "$result" | jq -r '.data.deployments.edges[0].node | "Status: \(.status)\nDeployment ID: \(.id)\nCommit: \(.meta.commitHash // "N/A" | .[0:7])\nMessage: \(.meta.commitMessage // "N/A")\nBranch: \(.meta.branch // "N/A")\nCreated: \(.createdAt)"'
  else
    echo "$result"
  fi
}

# Get deployment logs
cmd_logs() {
  local limit="${1:-50}"

  # First get the latest deployment ID
  local deploy_query="query { deployments(first: 1, input: { serviceId: \\\"$RAILWAY_SERVICE_ID\\\", environmentId: \\\"$RAILWAY_ENVIRONMENT_ID\\\" }) { edges { node { id } } } }"
  local deploy_result=$(railway_query "$deploy_query")

  local deployment_id=""
  if command -v jq &> /dev/null; then
    deployment_id=$(echo "$deploy_result" | jq -r '.data.deployments.edges[0].node.id')
  else
    echo "Error: jq is required for logs command"
    exit 1
  fi

  if [ -z "$deployment_id" ] || [ "$deployment_id" = "null" ]; then
    echo "Error: No deployment found"
    exit 1
  fi

  local log_query="query { deploymentLogs(deploymentId: \\\"$deployment_id\\\", limit: $limit) { timestamp message severity } }"
  local result=$(railway_query "$log_query")

  if command -v jq &> /dev/null; then
    echo "$result" | jq -r '.data.deploymentLogs[] | "\(.timestamp) [\(.severity // "INFO")] \(.message)"' 2>/dev/null || echo "$result"
  else
    echo "$result"
  fi
}

# List recent deployments
cmd_deployments() {
  local limit="${1:-5}"
  local query="query { deployments(first: $limit, input: { serviceId: \\\"$RAILWAY_SERVICE_ID\\\", environmentId: \\\"$RAILWAY_ENVIRONMENT_ID\\\" }) { edges { node { id status createdAt meta { commitHash commitMessage } } } } }"

  local result=$(railway_query "$query")

  if command -v jq &> /dev/null; then
    echo "Recent Deployments:"
    echo "$result" | jq -r '.data.deployments.edges[] | .node | "  \(.id | .[0:8])  \(.status | .[0:10])  \(.meta.commitHash // "N/A" | .[0:7])  \(.meta.commitMessage // "No message" | .[0:40])"'
  else
    echo "$result"
  fi
}

# Trigger redeploy
cmd_redeploy() {
  local query="mutation { serviceInstanceRedeploy(serviceId: \\\"$RAILWAY_SERVICE_ID\\\", environmentId: \\\"$RAILWAY_ENVIRONMENT_ID\\\") { id } }"

  local result=$(railway_query "$query")

  if command -v jq &> /dev/null; then
    local new_id=$(echo "$result" | jq -r '.data.serviceInstanceRedeploy.id // empty')
    if [ -n "$new_id" ]; then
      echo "Redeploy triggered successfully!"
      echo "New deployment ID: $new_id"
    else
      echo "Error: $(echo "$result" | jq -r '.errors[0].message // "Unknown error"')"
      exit 1
    fi
  else
    echo "$result"
  fi
}

# Rollback to a specific deployment
cmd_rollback() {
  local deployment_id="$1"

  if [ -z "$deployment_id" ]; then
    echo "Error: Deployment ID required"
    echo "Usage: railway.sh rollback <deployment-id>"
    exit 1
  fi

  local query="mutation { deploymentRollback(id: \\\"$deployment_id\\\") { id } }"

  local result=$(railway_query "$query")

  if command -v jq &> /dev/null; then
    local new_id=$(echo "$result" | jq -r '.data.deploymentRollback.id // empty')
    if [ -n "$new_id" ]; then
      echo "Rollback successful!"
      echo "New deployment ID: $new_id"
    else
      echo "Error: $(echo "$result" | jq -r '.errors[0].message // "Unknown error"')"
      exit 1
    fi
  else
    echo "$result"
  fi
}

# Get service info
cmd_info() {
  local query="query { service(id: \\\"$RAILWAY_SERVICE_ID\\\") { name deployments(first: 1) { edges { node { status staticUrl } } } } }"

  local result=$(railway_query "$query")

  if command -v jq &> /dev/null; then
    echo "$result" | jq -r '.data.service | "Service: \(.name)\nStatus: \(.deployments.edges[0].node.status // "unknown")\nURL: \(.deployments.edges[0].node.staticUrl // "N/A")"'
  else
    echo "$result"
  fi
}

# Main command router
case "${1:-help}" in
  status)
    cmd_status
    ;;
  logs)
    cmd_logs "$2"
    ;;
  deployments|list)
    cmd_deployments "$2"
    ;;
  redeploy|deploy)
    cmd_redeploy
    ;;
  rollback)
    cmd_rollback "$2"
    ;;
  info)
    cmd_info
    ;;
  help|--help|-h)
    echo "Railway CLI wrapper"
    echo ""
    echo "Commands:"
    echo "  status          - Get current deployment status"
    echo "  logs [limit]    - Get deployment logs (default: 50)"
    echo "  deployments [n] - List recent deployments (default: 5)"
    echo "  redeploy        - Trigger a redeploy"
    echo "  rollback <id>   - Rollback to a specific deployment"
    echo "  info            - Get service information"
    ;;
  *)
    echo "Unknown command: $1"
    echo "Run '$0 help' for usage"
    exit 1
    ;;
esac
