#!/bin/bash

# Build optimized Tumblr Agent Docker image with size analysis

set -e

echo "🏗️  Building optimized Tumblr Agent Docker image..."

# Build the image
docker build -f docker/Dockerfile -t tumblr-agent:optimized .

# Show image size
echo ""
echo "📊 Image Size Analysis:"
echo "======================"

# Show the built image size
docker images | grep tumblr-agent | grep optimized

# Show layer sizes
echo ""
echo "🔍 Layer Analysis:"
echo "=================="
docker history tumblr-agent:optimized --format "table {{.CreatedBy}}\t{{.Size}}" | head -20

# Clean up dangling images
echo ""
echo "🧹 Cleaning up dangling images..."
docker image prune -f

echo ""
echo "✅ Build completed! Image tagged as: tumblr-agent:optimized"
echo ""
echo "💡 Additional size reduction tips:"
echo "   - Consider using distroless images for even smaller size"
echo "   - Remove unused Python packages from requirements-prod.txt"
echo "   - Use multi-stage builds to exclude build tools from final image"
echo "   - Compress large files before COPY operations" 