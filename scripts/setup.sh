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

# Main setup flow
main() {
    print_banner

    echo "This wizard will help you set up your Claude Software Factory."
    echo "It will configure your project, create GitHub labels, and prepare"
    echo "everything for autonomous AI-powered development."
    echo ""

    # Check prerequisites
    step "1" "Checking Prerequisites"

    local missing_deps=()

    if check_command gh; then
        success "GitHub CLI (gh) is installed"

        # Check if authenticated
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

    if [ ${#missing_deps[@]} -gt 0 ]; then
        echo ""
        error "Missing required dependencies. Please install them and run this script again."
        exit 1
    fi

    # Get repository info
    step "2" "Project Configuration"

    # Try to detect repo info
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

    # Production URLs (optional)
    step "3" "Production Configuration (Optional)"

    echo "If you have production URLs, the DevOps agent can monitor them."
    echo "Leave blank to skip (you can add these later in GitHub Secrets)."
    echo ""

    prompt "Production backend URL (e.g., https://api.example.com)" "" PROD_BACKEND
    prompt "Production frontend URL (e.g., https://example.com)" "" PROD_FRONTEND

    # Create labels
    step "4" "Creating GitHub Labels"

    echo "Creating labels for issue tracking and agent triggers..."
    echo ""

    create_labels() {
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
            if gh label create "$name" --color "$color" --description "$desc" --repo "$REPO" 2>/dev/null; then
                success "Created label: $name"
            else
                # Label might already exist, try to update it
                if gh label edit "$name" --color "$color" --description "$desc" --repo "$REPO" 2>/dev/null; then
                    info "Updated existing label: $name"
                else
                    warn "Could not create/update label: $name (may already exist)"
                fi
            fi
        done
    }

    if confirm "Create GitHub labels now?"; then
        create_labels
    else
        info "Skipping label creation. You can run this later:"
        echo "  ./scripts/setup.sh --labels-only"
    fi

    # Update CLAUDE.md
    step "5" "Updating Project Configuration"

    echo "Updating CLAUDE.md with your project details..."

    # Create a backup
    cp CLAUDE.md CLAUDE.md.bak

    # Update the placeholder sections
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
    step "6" "Setup Complete!"

    echo -e "${GREEN}"
    echo "╔═══════════════════════════════════════════════════════════════╗"
    echo "║                 🎉  Setup Complete!  🎉                       ║"
    echo "╚═══════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"

    echo ""
    echo -e "${BOLD}Your software factory is almost ready!${NC}"
    echo ""
    echo "Next steps:"
    echo ""
    echo -e "${YELLOW}1. Add GitHub Secrets${NC} (required for agents to work)"
    echo "   Go to: https://github.com/$REPO/settings/secrets/actions"
    echo ""
    echo "   Required secrets:"
    echo "   • ANTHROPIC_API_KEY - Your Anthropic API key"
    echo "   • PAT_WITH_WORKFLOW_ACCESS - GitHub PAT with repo+workflow scopes"
    echo ""
    if [ -n "$PROD_BACKEND" ] || [ -n "$PROD_FRONTEND" ]; then
        echo "   Optional (for production monitoring):"
        [ -n "$PROD_BACKEND" ] && echo "   • PRODUCTION_BACKEND_URL = $PROD_BACKEND"
        [ -n "$PROD_FRONTEND" ] && echo "   • PRODUCTION_FRONTEND_URL = $PROD_FRONTEND"
        echo ""
    fi

    echo -e "${YELLOW}2. Enable Actions Permissions${NC}"
    echo "   Go to: https://github.com/$REPO/settings/actions"
    echo "   • Allow all actions"
    echo "   • Enable 'Read and write permissions'"
    echo "   • Check 'Allow GitHub Actions to create and approve pull requests'"
    echo ""

    echo -e "${YELLOW}3. Test the Factory${NC}"
    echo "   Create a test issue to verify everything works:"
    echo "   gh issue create --title 'Test: Hello from the factory' --body 'Verify agents are working'"
    echo ""

    if [ "$USE_STARTERS" = "yes" ]; then
        echo -e "${YELLOW}4. Start Developing${NC}"
        echo "   Backend: cd backend && uv sync && uv run uvicorn app.main:app --reload"
        echo "   Frontend: cd frontend && npm install && npm run dev"
        echo ""
    fi

    echo "For detailed documentation, see:"
    echo "• README.md - Full setup guide"
    echo "• CLAUDE.md - Agent instructions and philosophy"
    echo "• GETTING_STARTED.md - Quick start guide"
    echo ""

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

# Handle command line arguments
case "${1:-}" in
    --labels-only)
        REPO=$(git remote get-url origin | sed 's/.*github.com[:/]\(.*\)\.git/\1/' | sed 's/.*github.com[:/]\(.*\)/\1/')
        echo "Creating labels for $REPO..."
        create_labels
        ;;
    --help|-h)
        echo "Claude Software Factory Setup Wizard"
        echo ""
        echo "Usage: ./scripts/setup.sh [OPTIONS]"
        echo ""
        echo "Options:"
        echo "  --labels-only  Only create GitHub labels"
        echo "  --help, -h     Show this help message"
        echo ""
        ;;
    *)
        main
        ;;
esac
