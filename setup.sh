#!/usr/bin/env bash
set -euo pipefail

# Quick setup script for Mittwald Open WebUI

log() {
	echo "📋 $*" >&2
}

success() {
	echo "✅ $*" >&2
}

error() {
	echo "❌ $*" >&2
	exit 1
}

warn() {
	echo "⚠️  $*" >&2
}

# Check prerequisites
log "Checking prerequisites..."

if ! command -v docker &>/dev/null; then
	error "Docker is not installed. Please install Docker first."
fi

if ! command -v python3 &>/dev/null; then
	error "Python 3 is not installed. Please install Python 3 first."
fi

success "Docker and Python 3 are installed"

# Install Python dependencies
log "Installing Python dependencies..."
pip3 install requests beautifulsoup4 --quiet --user 2>/dev/null || {
	warn "Failed to install dependencies via pip. Trying with --break-system-packages..."
	pip3 install requests beautifulsoup4 --quiet --break-system-packages 2>/dev/null || {
		warn "Could not install dependencies. Some scraping features may not work."
	}
}

success "Python dependencies installed (or already present)"

# Create .env file if it doesn't exist
if [ ! -f .env ]; then
	log "Creating .env file from .env.example..."
	cp .env.example .env
	success "Created .env file. Please edit it with your credentials."
	warn "⚠️  IMPORTANT: Update .env with your Docker Hub credentials and API tokens"
else
	log ".env file already exists"
fi

# Make scripts executable
log "Making scripts executable..."
chmod +x scripts/*.sh 2>/dev/null || true
chmod +x bootstrap/*.sh 2>/dev/null || true
success "Scripts are executable"

# Check if git repository
if [ -d .git ]; then
	log "Git repository detected"
	git remote -v || warn "No git remote configured"
fi

# Display next steps
cat <<'EOF'

🎉 Setup complete!

Next steps:

1. Configure environment variables:
   Edit .env file with your credentials:
   - DOCKER_USERNAME
   - DOCKER_PASSWORD
   - HUGGINGFACE_TOKEN (optional)
   - MITTWALD_API_TOKEN (optional)

2. Configure GitHub Secrets:
   See SETUP.md for detailed instructions:
   - DOCKER_USERNAME
   - DOCKER_PASSWORD
   - HUGGINGFACE_TOKEN (optional)
   - MITTWALD_API_TOKEN (optional)

3. Test locally:
   make build
   make test

4. Push to GitHub:
   git add .
   git commit -m "Initial setup"
   git push

5. Trigger workflow:
   Go to Actions tab in GitHub and run "Monitor & Deploy Open WebUI"

For more information, see:
- README.md - Complete documentation
- SETUP.md - GitHub Actions setup guide
- Makefile - Available commands

Useful commands:
- make help     - Show all available commands
- make build    - Build Docker image
- make test     - Run tests
- make scrape   - Run scrapers

EOF
