# Multi-stage build for Tumblr Upload Agent System
FROM python:3.11-slim as builder

# Add container labels for GitHub Container Registry
LABEL org.opencontainers.image.source="https://github.com/jtenniswood/tumblr-agent"
LABEL org.opencontainers.image.description="Multi-agent system for automatically uploading images to Tumblr with AI-powered descriptions"
LABEL org.opencontainers.image.licenses="MIT"

# Set environment variables (rarely changes)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies for building (this layer rarely changes)
RUN apt-get update && apt-get install -y \
    build-essential \
    gcc \
    libavif-dev \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment (this layer rarely changes)
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy requirements first (separate from code for better caching)
COPY requirements.txt .

# Install Python dependencies (this layer only rebuilds when requirements.txt changes)
RUN pip install --upgrade pip setuptools wheel && \
    pip install -r requirements.txt

# Production stage
FROM python:3.11-slim as production

# Set environment variables (rarely changes)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/app"

# Install runtime dependencies (this layer rarely changes)
RUN apt-get update && apt-get install -y \
    procps \
    gosu \
    libavif-dev \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Create non-root user with UID 1000 (common host user UID)
RUN groupadd -g 1000 tumblr && useradd -r -u 1000 -g tumblr tumblr

# Copy virtual environment from builder (only rebuilds if deps change)
COPY --from=builder /opt/venv /opt/venv

# Create application directory and data dirs (rarely changes)
WORKDIR /app
RUN mkdir -p /app/data/upload /app/data/failed

# Copy only the application code (this changes most frequently)
# This way, code changes don't invalidate the expensive dependency layers above
COPY --chown=tumblr:tumblr app/ ./app/
COPY --chown=tumblr:tumblr requirements.txt .

# Create entrypoint script to handle permissions
COPY <<EOF /entrypoint.sh
#!/bin/bash
set -e

echo "🔧 Setting up user and permissions..."

# Get PUID and PGID from environment (default to 1000)
PUID=\${PUID:-1000}
PGID=\${PGID:-1000}

echo "Target PUID: \$PUID"
echo "Target PGID: \$PGID"

# If running as root (PUID=0), skip user switching
if [ "\$PUID" = "0" ]; then
    echo "🚀 Running as root user..."
    
    # Ensure data directories exist and have proper permissions
    mkdir -p /app/data/upload /app/data/failed
    chmod -R 755 /app/data/
    
    # Run directly as root
    exec "\$@"
else
    echo "🔧 Setting up non-root user (PUID=\$PUID, PGID=\$PGID)..."
    
    # Update the tumblr user/group to match PUID/PGID
    groupmod -o -g "\$PGID" tumblr 2>/dev/null || echo "Group update skipped"
    usermod -o -u "\$PUID" tumblr 2>/dev/null || echo "User update skipped"
    
    # Show current user and permissions for debugging
    echo "Current user: \$(whoami)"
    echo "Current UID: \$(id -u)"
    echo "Data directory permissions before:"
    ls -la /app/data/ || echo "Data directory doesn't exist yet"
    
    # Ensure data directories exist
    mkdir -p /app/data/upload /app/data/failed
    
    # Fix ownership and permissions
    chown -R "\$PUID:\$PGID" /app/data/ 2>/dev/null || echo "Warning: Could not change ownership"
    chmod -R 755 /app/data/ 2>/dev/null || echo "Warning: Could not change permissions"
    
    echo "Data directory permissions after:"
    ls -la /app/data/
    
    echo "🚀 Starting Tumblr Upload Agent as user tumblr (UID=\$PUID)..."
    exec gosu tumblr "\$@"
fi
EOF

RUN chmod +x /entrypoint.sh

# Health check using process monitoring instead of HTTP
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD ps aux | grep -v grep | grep -q "python.*main.py" || exit 1

ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "-m", "app.main"] 