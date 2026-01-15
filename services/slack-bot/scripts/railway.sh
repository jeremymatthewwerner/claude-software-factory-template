#!/bin/bash

# Railway Management Script for Claude Software Factory Slack Bot
# This script provides convenient commands for managing the Railway deployment

set -e

# Check if railway CLI is available
if ! command -v railway &> /dev/null; then
    echo "⚠️  Railway CLI not found. Installing..."
    curl -fsSL https://railway.app/install.sh | sh
    export PATH="$HOME/.railway/bin:$PATH"
fi

# Function to check Railway authentication
check_auth() {
    if [[ -z "$RAILWAY_TOKEN" ]]; then
        echo "❌ RAILWAY_TOKEN environment variable not set"
        echo "Please set RAILWAY_TOKEN to your Railway project token"
        return 1
    fi
    export RAILWAY_TOKEN
}

# Function to make health check without Railway CLI
health_check() {
    echo "🔍 Checking service health..."
    local health_url="https://claude-software-factory-template-production.up.railway.app/health"

    if curl -s "$health_url" > /dev/null; then
        echo "✅ Service is healthy"
        curl -s "$health_url" | jq '.' 2>/dev/null || curl -s "$health_url"
    else
        echo "❌ Service health check failed"
        return 1
    fi
}

# Function to show usage
show_usage() {
    echo "Railway Management Script"
    echo ""
    echo "Usage: $0 <command> [args]"
    echo ""
    echo "Commands:"
    echo "  status               - Show deployment status"
    echo "  logs [lines]         - View recent logs (default: 100)"
    echo "  deployments [count]  - List recent deployments (default: 10)"
    echo "  redeploy            - Trigger manual redeploy"
    echo "  rollback <id>       - Rollback to specific deployment"
    echo "  info                - Show service information"
    echo "  health              - Check service health (no auth required)"
    echo "  help                - Show this help message"
}

# Main command dispatcher
case "$1" in
    "status")
        echo "🔍 Checking deployment status..."
        if check_auth; then
            railway status
        else
            health_check
        fi
        ;;

    "logs")
        LINES=${2:-100}
        echo "📋 Fetching last $LINES log lines..."
        if check_auth; then
            railway logs --lines "$LINES"
        else
            echo "❌ Railway CLI authentication required for logs"
            exit 1
        fi
        ;;

    "deployments")
        COUNT=${2:-10}
        echo "📦 Listing last $COUNT deployments..."
        if check_auth; then
            railway deployments --limit "$COUNT"
        else
            echo "❌ Railway CLI authentication required for deployments"
            exit 1
        fi
        ;;

    "redeploy")
        echo "🚀 Triggering manual redeploy..."
        if check_auth; then
            railway redeploy
            echo "✅ Redeploy triggered"
        else
            echo "❌ Railway CLI authentication required for redeploy"
            exit 1
        fi
        ;;

    "rollback")
        if [[ -z "$2" ]]; then
            echo "❌ Deployment ID required"
            echo "Usage: $0 rollback <deployment-id>"
            echo "Get deployment ID with: $0 deployments"
            exit 1
        fi
        echo "⏪ Rolling back to deployment $2..."
        if check_auth; then
            railway rollback "$2"
            echo "✅ Rollback completed"
        else
            echo "❌ Railway CLI authentication required for rollback"
            exit 1
        fi
        ;;

    "info")
        echo "ℹ️  Service information..."
        if check_auth; then
            railway status
            echo ""
            railway variables
        else
            echo "❌ Railway CLI authentication required for detailed info"
            health_check
        fi
        ;;

    "health")
        health_check
        ;;

    "help"|"--help"|"-h")
        show_usage
        ;;

    "")
        echo "❌ No command specified"
        show_usage
        exit 1
        ;;

    *)
        echo "❌ Unknown command: $1"
        show_usage
        exit 1
        ;;
esac