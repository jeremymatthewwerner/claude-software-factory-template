#!/bin/bash
#
# Claude Software Factory - Setup Wizard
# This script helps you configure your software factory after forking/cloning the template.
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m' # No Color
BOLD='\033[1m'

# Print banner
print_banner() {
    echo -e "${CYAN}"
    echo "╔═══════════════════════════════════════════════════════════════╗"
    echo "║                                                               ║"
    echo "║        🏭  Claude Software Factory Setup Wizard  🏭          ║"
    echo "║                                                               ║"
    echo "║   Transform your repo into an autonomous development team    ║"
    echo "║                                                               ║"
    echo "╚═══════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

# Print step header
step() {
    echo ""
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BOLD}Step $1: $2${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

# Print success message
success() {
    echo -e "${GREEN}✓ $1${NC}"
}

# Print warning message
warn() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

# Print error message
error() {
    echo -e "${RED}✗ $1${NC}"
}

# Print info message
info() {
    echo -e "${CYAN}ℹ $1${NC}"
}

# Check if command exists
check_command() {
    if command -v "$1" &> /dev/null; then
        return 0
    else
        return 1
    fi
}

# Prompt for input with default
prompt() {
    local prompt_text="$1"
    local default="$2"
    local var_name="$3"

    if [ -n "$default" ]; then
        read -p "$prompt_text [$default]: " value
        value="${value:-$default}"
    else
        read -p "$prompt_text: " value
    fi

    eval "$var_name='$value'"
}

# Prompt for yes/no
confirm() {
    local prompt_text="$1"
    local default="${2:-y}"

    if [ "$default" = "y" ]; then
        read -p "$prompt_text [Y/n]: " response
        response="${response:-y}"
    else
        read -p "$prompt_text [y/N]: " response
        response="${response:-n}"
    fi

    case "$response" in
        [yY][eE][sS]|[yY]) return 0 ;;
        *) return 1 ;;
    esac
}

# Menu selection
select_option() {
    local prompt_text="$1"
    shift
    local options=("$@")

    echo "$prompt_text"
    for i in "${!options[@]}"; do
        echo "  $((i+1))) ${options[$i]}"
    done

    while true; do
        read -p "Enter choice [1-${#options[@]}]: " choice
        if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le "${#options[@]}" ]; then
            SELECTED_OPTION="${options[$((choice-1))]}"
            SELECTED_INDEX=$((choice-1))
            return 0
        fi
        echo "Invalid choice. Please enter 1-${#options[@]}"
    done
}

# Create GitHub labels
create_labels() {
    local repo="$1"
    local labels=(
        "ai-ready|0E8A16|Ready for autonomous agent"
        "needs-principal-engineer|7057FF|Escalated to PE (Code Agent stuck)"
        "needs-human|D93F0B|Requires human intervention"
        "qa-agent|0052CC|QA Agent tracking"
        "automation|BFDADC|Automated by agents"
        "ci-failure|B60205|CI failure issues"
        "production-incident|B60205|Production incidents"
        "status:bot-working|7057FF|Bot is actively working"
        "status:awaiting-human|D93F0B|Blocked waiting for human"
        "status:awaiting-bot|0E8A16|Human commented, bot will respond"
        "bug|d73a4a|Something isn't working"
        "enhancement|a2eeef|New feature or request"
        "priority-high|B60205|High priority"
        "priority-medium|FBCA04|Medium priority"
        "priority-low|0E8A16|Low priority"
        "P0|B60205|Critical - system down"
        "P1|D93F0B|High - blocks functionality"
        "P2|FBCA04|Medium - optimization/cleanup"
    )

    for label_def in "${labels[@]}"; do
        IFS='|' read -r name color desc <<< "$label_def"
        if gh label create "$name" --color "$color" --description "$desc" --repo "$repo" 2>/dev/null; then
            success "Created label: $name"
        else
            if gh label edit "$name" --color "$color" --description "$desc" --repo "$repo" 2>/dev/null; then
                info "Updated existing label: $name"
            else
                warn "Could not create/update label: $name (may already exist)"
            fi
        fi
    done
}

# Set GitHub secret
set_github_secret() {
    local repo="$1"
    local name="$2"
    local value="$3"

    echo "$value" | gh secret set "$name" --repo "$repo" 2>/dev/null
    return $?
}

# Main setup flow
main() {
    print_banner

    echo "This wizard will help you set up your Claude Software Factory."
    echo "It will configure your project, create GitHub labels, set up"
    echo "deployment, and prepare everything for autonomous development."
    echo ""

    # Check prerequisites
    step "1" "Checking Prerequisites"

    local missing_deps=()

    if check_command gh; then
        success "GitHub CLI (gh) is installed"
        if gh auth status &> /dev/null; then
            success "GitHub CLI is authenticated"
        else
            error "GitHub CLI is not authenticated"
            echo "  Run: gh auth login"
            missing_deps+=("gh-auth")
        fi
    else
        error "GitHub CLI (gh) is not installed"
        echo "  Install: https://cli.github.com/"
        missing_deps+=("gh")
    fi

    if check_command git; then
        success "Git is installed"
    else
        error "Git is not installed"
        missing_deps+=("git")
    fi

    if check_command node; then
        success "Node.js is installed ($(node --version))"
    else
        warn "Node.js is not installed (needed for frontend)"
        echo "  Install: https://nodejs.org/"
    fi

    if check_command python3 || check_command python; then
        success "Python is installed"
    else
        warn "Python is not installed (needed for backend)"
    fi

    if check_command uv; then
        success "uv is installed (fast Python package manager)"
    else
        warn "uv is not installed (recommended for backend)"
        echo "  Install: curl -LsSf https://astral.sh/uv/install.sh | sh"
    fi

    # Check for Railway CLI (optional)
    RAILWAY_AVAILABLE=false
    if check_command railway; then
        success "Railway CLI is installed"
        RAILWAY_AVAILABLE=true
    else
        info "Railway CLI not installed (optional, for deployment)"
        echo "  Install: npm install -g @railway/cli"
    fi

    if [ ${#missing_deps[@]} -gt 0 ]; then
        echo ""
        error "Missing required dependencies. Please install them and run this script again."
        exit 1
    fi

    # Get repository info
    step "2" "Project Configuration"

    local detected_repo=""
    if git remote get-url origin &> /dev/null; then
        detected_repo=$(git remote get-url origin | sed 's/.*github.com[:/]\(.*\)\.git/\1/' | sed 's/.*github.com[:/]\(.*\)/\1/')
    fi

    prompt "GitHub repository (owner/repo)" "$detected_repo" REPO
    prompt "Project name" "$(basename "$REPO")" PROJECT_NAME
    prompt "Project description" "An autonomous software factory powered by Claude" PROJECT_DESC
    prompt "Your GitHub username (for escalations)" "$(echo $REPO | cut -d'/' -f1)" MAINTAINER

    echo ""
    info "Tech Stack Selection"
    echo "This template includes a starter backend (FastAPI) and frontend (Next.js)."
    echo "You can customize or replace these after setup."
    echo ""

    if confirm "Use the included Hello World starter apps?"; then
        USE_STARTERS="yes"
    else
        USE_STARTERS="no"
    fi

    # Deployment Configuration
    step "3" "Deployment Configuration"

    echo ""
    echo "How would you like to deploy your application?"
    echo ""
    select_option "Choose deployment option:" \
        "Railway (recommended - easy setup, free tier)" \
        "Vercel + separate backend (frontend on Vercel)" \
        "Self-hosted / Docker" \
        "Skip deployment setup (configure later)"

    DEPLOY_OPTION=$SELECTED_INDEX

    PROD_BACKEND=""
    PROD_FRONTEND=""
    RAILWAY_PROJECT_ID=""
    CUSTOM_DOMAIN=""

    case $DEPLOY_OPTION in
        0)  # Railway
            setup_railway_deployment
            ;;
        1)  # Vercel
            echo ""
            info "Vercel deployment selected"
            echo "You'll deploy the frontend to Vercel and backend separately."
            echo ""
            prompt "Backend URL (leave blank to set up later)" "" PROD_BACKEND
            prompt "Frontend URL (e.g., your-project.vercel.app)" "" PROD_FRONTEND
            ;;
        2)  # Self-hosted
            echo ""
            info "Self-hosted deployment selected"
            echo ""
            prompt "Production backend URL" "" PROD_BACKEND
            prompt "Production frontend URL" "" PROD_FRONTEND
            ;;
        3)  # Skip
            info "Skipping deployment setup. You can run './scripts/setup-railway.sh' later."
            ;;
    esac

    # Create labels
    step "4" "Creating GitHub Labels"

    echo "Creating labels for issue tracking and agent triggers..."
    echo ""

    if confirm "Create GitHub labels now?"; then
        create_labels "$REPO"
    else
        info "Skipping label creation. You can run this later:"
        echo "  ./scripts/setup.sh --labels-only"
    fi

    # GitHub Secrets
    step "5" "GitHub Secrets Configuration"

    echo "The software factory needs these secrets to operate:"
    echo ""
    echo "  ${BOLD}Required:${NC}"
    echo "  • ANTHROPIC_API_KEY - Powers the AI agents"
    echo "  • PAT_WITH_WORKFLOW_ACCESS - Allows agents to create PRs"
    echo ""
    echo "  ${BOLD}Optional:${NC}"
    echo "  • PRODUCTION_BACKEND_URL - For DevOps monitoring"
    echo "  • PRODUCTION_FRONTEND_URL - For DevOps monitoring"
    echo "  • RAILWAY_TOKEN_SW_FACTORY - For auto-deployment"
    echo ""

    if confirm "Would you like to set up GitHub secrets now?"; then
        setup_github_secrets
    else
        info "Skipping secrets setup. Add them manually at:"
        echo "  https://github.com/$REPO/settings/secrets/actions"
    fi

    # Update CLAUDE.md
    step "6" "Updating Project Configuration"

    echo "Updating CLAUDE.md with your project details..."

    cp CLAUDE.md CLAUDE.md.bak

    sed -i "s/\[Your Project Name\]/$PROJECT_NAME/g" CLAUDE.md
    sed -i "s/\[Your project description\]/$PROJECT_DESC/g" CLAUDE.md
    sed -i "s/\[Your production URL\]/${PROD_FRONTEND:-https://your-domain.com}/g" CLAUDE.md
    sed -i "s/@\[your-github-username\]/@$MAINTAINER/g" CLAUDE.md

    success "Updated CLAUDE.md"

    # Activate CI workflow
    if [ -f ".github/workflows/ci.yml.example" ] && [ ! -f ".github/workflows/ci.yml" ]; then
        cp .github/workflows/ci.yml.example .github/workflows/ci.yml
        success "Activated CI workflow (ci.yml)"
    fi

    # Summary and next steps
    step "7" "Setup Complete!"

    echo -e "${GREEN}"
    echo "╔═══════════════════════════════════════════════════════════════╗"
    echo "║                 🎉  Setup Complete!  🎉                       ║"
    echo "╚═══════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"

    echo ""
    echo -e "${BOLD}Your software factory is ready!${NC}"
    echo ""

    # Show what was configured
    echo -e "${MAGENTA}Configuration Summary:${NC}"
    echo "  • Project: $PROJECT_NAME"
    echo "  • Repository: $REPO"
    echo "  • Maintainer: @$MAINTAINER"
    [ -n "$PROD_BACKEND" ] && echo "  • Backend URL: $PROD_BACKEND"
    [ -n "$PROD_FRONTEND" ] && echo "  • Frontend URL: $PROD_FRONTEND"
    [ -n "$RAILWAY_PROJECT_ID" ] && echo "  • Railway Project: $RAILWAY_PROJECT_ID"
    echo ""

    # Remaining manual steps
    local manual_steps=()

    if [ -z "$ANTHROPIC_API_KEY_SET" ]; then
        manual_steps+=("Add ANTHROPIC_API_KEY to GitHub Secrets")
    fi
    if [ -z "$PAT_SET" ]; then
        manual_steps+=("Add PAT_WITH_WORKFLOW_ACCESS to GitHub Secrets")
    fi

    if [ ${#manual_steps[@]} -gt 0 ]; then
        echo -e "${YELLOW}Remaining manual steps:${NC}"
        for step in "${manual_steps[@]}"; do
            echo "  • $step"
        done
        echo ""
        echo "  Go to: https://github.com/$REPO/settings/secrets/actions"
        echo ""
    fi

    echo -e "${YELLOW}Enable Actions Permissions:${NC}"
    echo "  Go to: https://github.com/$REPO/settings/actions"
    echo "  • Allow all actions"
    echo "  • Enable 'Read and write permissions'"
    echo "  • Check 'Allow GitHub Actions to create and approve pull requests'"
    echo ""

    echo -e "${YELLOW}Test the Factory:${NC}"
    echo "  gh issue create --title 'Test: Hello from the factory' --body 'Verify agents are working'"
    echo ""

    if [ "$USE_STARTERS" = "yes" ]; then
        echo -e "${YELLOW}Start Developing:${NC}"
        echo "  Backend:  cd backend && uv sync && uv run uvicorn app.main:app --reload"
        echo "  Frontend: cd frontend && npm install && npm run dev"
        echo ""
    fi

    if confirm "Would you like to commit these setup changes?"; then
        git add -A
        git commit -m "chore: configure software factory for $PROJECT_NAME

- Update CLAUDE.md with project details
- Activate CI workflow
- Configure for maintainer @$MAINTAINER"
        success "Changes committed!"

        if confirm "Push to remote?"; then
            git push
            success "Changes pushed!"
        fi
    fi

    echo ""
    echo -e "${CYAN}Happy building! Your AI team is ready to help. 🤖${NC}"
    echo ""
}

# Railway deployment setup
setup_railway_deployment() {
    echo ""
    info "Railway Deployment Setup"
    echo ""

    if ! $RAILWAY_AVAILABLE; then
        warn "Railway CLI is not installed."
        echo ""
        if confirm "Would you like to install it now?"; then
            npm install -g @railway/cli
            if check_command railway; then
                success "Railway CLI installed"
                RAILWAY_AVAILABLE=true
            else
                error "Failed to install Railway CLI"
                echo "Please install manually: npm install -g @railway/cli"
                return 1
            fi
        else
            echo ""
            echo "Without Railway CLI, you'll need to set up manually:"
            echo "1. Go to https://railway.app/new"
            echo "2. Create a project and connect your GitHub repo"
            echo "3. Add RAILWAY_TOKEN_SW_FACTORY secret to GitHub"
            return 0
        fi
    fi

    # Check Railway auth
    if ! railway whoami &> /dev/null; then
        echo ""
        warn "Not logged into Railway"
        echo "Opening Railway login..."
        railway login
    fi

    success "Logged into Railway"
    echo ""

    # Project creation options
    select_option "Railway project setup:" \
        "Create a new Railway project" \
        "Link to existing Railway project" \
        "Skip Railway setup"

    case $SELECTED_INDEX in
        0)  # Create new project
            create_railway_project
            ;;
        1)  # Link existing
            link_railway_project
            ;;
        2)  # Skip
            info "Skipping Railway setup"
            return 0
            ;;
    esac

    # Domain configuration
    if [ -n "$RAILWAY_PROJECT_ID" ]; then
        echo ""
        configure_railway_domains
    fi
}

create_railway_project() {
    echo ""
    info "Creating new Railway project: $PROJECT_NAME"
    echo ""

    # Create the project
    if railway init --name "$PROJECT_NAME" 2>/dev/null; then
        success "Created Railway project"
        RAILWAY_PROJECT_ID=$(railway status --json 2>/dev/null | jq -r '.projectId' 2>/dev/null || echo "")

        if [ -n "$RAILWAY_PROJECT_ID" ]; then
            success "Project ID: $RAILWAY_PROJECT_ID"
        fi
    else
        error "Failed to create Railway project"
        echo "Please create manually at https://railway.app/new"
        return 1
    fi

    # Get Railway token for GitHub secret
    echo ""
    info "Generating Railway token for CI/CD..."
    echo ""
    echo "You need to create a Railway token for automated deployments:"
    echo "1. Go to: https://railway.app/account/tokens"
    echo "2. Create a new token named 'github-actions'"
    echo "3. Copy the token"
    echo ""

    prompt "Paste your Railway token (or press Enter to skip)" "" RAILWAY_TOKEN

    if [ -n "$RAILWAY_TOKEN" ]; then
        if confirm "Add RAILWAY_TOKEN_SW_FACTORY to GitHub secrets?"; then
            if set_github_secret "$REPO" "RAILWAY_TOKEN_SW_FACTORY" "$RAILWAY_TOKEN"; then
                success "Added Railway token to GitHub secrets"
            else
                warn "Failed to add secret. Add manually at:"
                echo "  https://github.com/$REPO/settings/secrets/actions"
            fi
        fi
    fi
}

link_railway_project() {
    echo ""
    info "Linking to existing Railway project"
    echo ""

    railway link

    RAILWAY_PROJECT_ID=$(railway status --json 2>/dev/null | jq -r '.projectId' 2>/dev/null || echo "")

    if [ -n "$RAILWAY_PROJECT_ID" ]; then
        success "Linked to project: $RAILWAY_PROJECT_ID"
    fi
}

configure_railway_domains() {
    echo ""
    info "Domain Configuration"
    echo ""
    echo "Railway provides free subdomains (*.up.railway.app)"
    echo "You can also add custom domains."
    echo ""

    select_option "Domain setup:" \
        "Use Railway subdomains (free, quickest)" \
        "Use custom domain (requires DNS configuration)" \
        "Configure both Railway subdomain and custom domain"

    case $SELECTED_INDEX in
        0)  # Railway subdomains only
            setup_railway_subdomains
            ;;
        1)  # Custom domain only
            setup_custom_domain
            ;;
        2)  # Both
            setup_railway_subdomains
            setup_custom_domain
            ;;
    esac
}

setup_railway_subdomains() {
    echo ""
    info "Railway Subdomain Setup"
    echo ""
    echo "Railway will generate subdomains for your services."
    echo "After deployment, your URLs will be something like:"
    echo "  • Backend:  ${PROJECT_NAME}-backend.up.railway.app"
    echo "  • Frontend: ${PROJECT_NAME}-frontend.up.railway.app"
    echo ""

    # Set expected URLs (actual URLs come after first deploy)
    PROD_BACKEND="https://${PROJECT_NAME}-backend.up.railway.app"
    PROD_FRONTEND="https://${PROJECT_NAME}-frontend.up.railway.app"

    info "These URLs will be active after your first deployment."
}

setup_custom_domain() {
    echo ""
    info "Custom Domain Setup"
    echo ""
    echo "Enter your custom domain (e.g., myapp.com)"
    echo "You'll need to configure DNS records after setup."
    echo ""

    prompt "Custom domain (e.g., myapp.com)" "" CUSTOM_DOMAIN

    if [ -n "$CUSTOM_DOMAIN" ]; then
        echo ""
        echo "For custom domain setup, you'll need to:"
        echo ""
        echo "1. In Railway Dashboard → Service → Settings → Domains:"
        echo "   Add: $CUSTOM_DOMAIN (frontend)"
        echo "   Add: api.$CUSTOM_DOMAIN (backend)"
        echo ""
        echo "2. In your DNS provider, add CNAME records:"
        echo "   ${BOLD}$CUSTOM_DOMAIN${NC} → CNAME → [railway-provided-domain]"
        echo "   ${BOLD}api.$CUSTOM_DOMAIN${NC} → CNAME → [railway-provided-domain]"
        echo ""
        echo "3. Railway will provide the exact CNAME targets"
        echo "   after you add the domains in their dashboard."
        echo ""

        PROD_BACKEND="https://api.$CUSTOM_DOMAIN"
        PROD_FRONTEND="https://$CUSTOM_DOMAIN"

        if confirm "Would you like to save these instructions to DEPLOYMENT.md?"; then
            create_deployment_guide
        fi
    fi
}

create_deployment_guide() {
    cat > DEPLOYMENT.md << EOF
# Deployment Guide

## Railway Configuration

Project: $PROJECT_NAME
Project ID: ${RAILWAY_PROJECT_ID:-"(set after creation)"}

## URLs

| Service | Railway Subdomain | Custom Domain |
|---------|-------------------|---------------|
| Backend | ${PROJECT_NAME}-backend.up.railway.app | api.$CUSTOM_DOMAIN |
| Frontend | ${PROJECT_NAME}-frontend.up.railway.app | $CUSTOM_DOMAIN |

## Custom Domain DNS Setup

Add these CNAME records in your DNS provider ($CUSTOM_DOMAIN):

\`\`\`
Type    Name    Value
CNAME   @       [from Railway - frontend service]
CNAME   api     [from Railway - backend service]
\`\`\`

### Steps:

1. Go to Railway Dashboard → Your Project
2. Click on the **frontend** service → Settings → Domains
3. Click "Add Domain" and enter: \`$CUSTOM_DOMAIN\`
4. Copy the CNAME target Railway provides
5. In your DNS provider, create a CNAME record pointing to that target
6. Repeat for **backend** service with \`api.$CUSTOM_DOMAIN\`

## Environment Variables

### Backend Service

\`\`\`
PORT=8000 (Railway sets this automatically)
DATABASE_URL=(if using database)
ANTHROPIC_API_KEY=(for any AI features in your app)
\`\`\`

### Frontend Service

\`\`\`
NEXT_PUBLIC_API_URL=https://api.$CUSTOM_DOMAIN
\`\`\`

## GitHub Secrets

These should be set in your GitHub repository:

| Secret | Value |
|--------|-------|
| ANTHROPIC_API_KEY | Your Anthropic API key |
| PAT_WITH_WORKFLOW_ACCESS | GitHub PAT with repo+workflow scopes |
| RAILWAY_TOKEN_SW_FACTORY | Railway API token |
| PRODUCTION_BACKEND_URL | https://api.$CUSTOM_DOMAIN |
| PRODUCTION_FRONTEND_URL | https://$CUSTOM_DOMAIN |

## First Deployment

After setting up, push to main to trigger deployment:

\`\`\`bash
git add -A
git commit -m "chore: initial deployment"
git push origin main
\`\`\`

The CI/CD workflow will build and deploy both services.
EOF
    success "Created DEPLOYMENT.md"
}

setup_github_secrets() {
    echo ""

    # Anthropic API Key
    echo -e "${BOLD}1. Anthropic API Key${NC}"
    echo "   Get yours at: https://console.anthropic.com/settings/keys"
    echo ""
    prompt "Anthropic API Key (paste or press Enter to skip)" "" ANTHROPIC_KEY

    if [ -n "$ANTHROPIC_KEY" ]; then
        if set_github_secret "$REPO" "ANTHROPIC_API_KEY" "$ANTHROPIC_KEY"; then
            success "Added ANTHROPIC_API_KEY to GitHub secrets"
            ANTHROPIC_API_KEY_SET=true
        else
            warn "Failed to add secret. Add manually."
        fi
    fi

    echo ""

    # GitHub PAT
    echo -e "${BOLD}2. GitHub Personal Access Token${NC}"
    echo "   Create at: https://github.com/settings/tokens?type=beta"
    echo ""
    echo "   Required permissions:"
    echo "   • Contents: Read and write"
    echo "   • Issues: Read and write"
    echo "   • Pull requests: Read and write"
    echo "   • Workflows: Read and write"
    echo "   • Actions: Read"
    echo ""
    prompt "GitHub PAT (paste or press Enter to skip)" "" GITHUB_PAT

    if [ -n "$GITHUB_PAT" ]; then
        if set_github_secret "$REPO" "PAT_WITH_WORKFLOW_ACCESS" "$GITHUB_PAT"; then
            success "Added PAT_WITH_WORKFLOW_ACCESS to GitHub secrets"
            PAT_SET=true
        else
            warn "Failed to add secret. Add manually."
        fi
    fi

    # Production URLs (if configured)
    if [ -n "$PROD_BACKEND" ]; then
        echo ""
        if confirm "Add PRODUCTION_BACKEND_URL ($PROD_BACKEND) to secrets?"; then
            if set_github_secret "$REPO" "PRODUCTION_BACKEND_URL" "$PROD_BACKEND"; then
                success "Added PRODUCTION_BACKEND_URL to GitHub secrets"
            fi
        fi
    fi

    if [ -n "$PROD_FRONTEND" ]; then
        if confirm "Add PRODUCTION_FRONTEND_URL ($PROD_FRONTEND) to secrets?"; then
            if set_github_secret "$REPO" "PRODUCTION_FRONTEND_URL" "$PROD_FRONTEND"; then
                success "Added PRODUCTION_FRONTEND_URL to GitHub secrets"
            fi
        fi
    fi
}

# Handle command line arguments
case "${1:-}" in
    --labels-only)
        REPO=$(git remote get-url origin | sed 's/.*github.com[:/]\(.*\)\.git/\1/' | sed 's/.*github.com[:/]\(.*\)/\1/')
        echo "Creating labels for $REPO..."
        create_labels "$REPO"
        ;;
    --railway)
        PROJECT_NAME=$(basename "$(pwd)")
        setup_railway_deployment
        ;;
    --secrets)
        REPO=$(git remote get-url origin | sed 's/.*github.com[:/]\(.*\)\.git/\1/' | sed 's/.*github.com[:/]\(.*\)/\1/')
        setup_github_secrets
        ;;
    --help|-h)
        echo "Claude Software Factory Setup Wizard"
        echo ""
        echo "Usage: ./scripts/setup.sh [OPTIONS]"
        echo ""
        echo "Options:"
        echo "  (none)         Run full interactive setup"
        echo "  --labels-only  Only create GitHub labels"
        echo "  --railway      Only run Railway deployment setup"
        echo "  --secrets      Only configure GitHub secrets"
        echo "  --help, -h     Show this help message"
        echo ""
        ;;
    *)
        main
        ;;
esac
