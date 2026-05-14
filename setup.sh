#!/bin/bash
# Volunteer Organization Map Setup Script
# Run this script to set up the volunteer map application

set -e  # Exit on error

echo "Setting up Volunteer Organization Map..."

# Install dependencies
echo "Installing Python dependencies..."
cd /opt/volunteer-map/backend
pip install -r requirements.txt

# Install Node dependencies for frontend (if package.json exists)
if [ -f "../frontend/package.json" ]; then
    echo "Installing frontend dependencies..."
    cd /opt/volunteer-map/frontend
    npm install
fi

# Create database
echo "Creating database..."
cd /opt/volunteer-map/backend
alembic upgrade head

# Seed database with sample data
echo "Seeding database with sample data..."
python scripts/seed_db.py

# Set up Cloudflare Tunnel (optional)
echo "Cloudflare Tunnel setup (optional):"
echo "1. Install Cloudflare Tunnel: https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/"
echo "2. Run: cloudflared tunnel create volunteer-map"
echo "3. Replace values in /opt/volunteer-map/cloudflare-tunnel-config.json"
echo "4. Run: cloudflared tunnel --config /opt/volunteer-map/cloudflare-tunnel-config.json run"

# Set up systemd service
echo "Setting up systemd service..."
sudo systemctl daemon-reload
sudo systemctl enable volunteer-map
sudo systemctl start volunteer-map

echo "Setup complete!"
echo "Frontend: http://localhost:3000 (run 'npm start' in frontend directory)"
echo "Backend: http://localhost:8000"
echo "API Docs: http://localhost:8000/docs"
