FROM node:22-slim AS builder

WORKDIR /app

# Copy package files
COPY package*.json ./

# Install ALL dependencies (including devDependencies for TypeScript build)
RUN npm ci

# Copy source code
COPY . .

# Build TypeScript
RUN npm run build

# Production stage
FROM node:22-slim

WORKDIR /app

# Install tools needed for Claude Code operations:
# - git: version control, clone repos, commit, push
# - curl: health checks, API calls
# - jq: JSON processing for Railway API
# - openssh-client: SSH for git operations
# - ca-certificates: HTTPS support
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    jq \
    openssh-client \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Configure git defaults
RUN git config --global user.email "bot@claude-factory.ai" && \
    git config --global user.name "Claude Factory Bot" && \
    git config --global init.defaultBranch main && \
    git config --global --add safe.directory '*'

# Create directory for cloned repos
RUN mkdir -p /tmp/repo

# Copy package files and install production deps only
COPY package*.json ./
RUN npm ci --only=production

# Copy built files from builder
COPY --from=builder /app/dist ./dist

# Copy scripts for Railway management
COPY --from=builder /app/scripts ./scripts

# Expose webhook port (Railway uses PORT env var)
EXPOSE 3000

# Health check using PORT env var
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${PORT:-3000}/health || exit 1

# Start the bot
CMD ["npm", "start"]
