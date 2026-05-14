#!/bin/bash
# Automated Deployment Script for volunteer.templeeearth.cc

set -e  # Exit on error

echo "🚀 Starting automated deployment for volunteer.templeeearth.cc..."

# 1. Install dependencies
echo "📦 Installing dependencies..."
cd /opt/volunteer-map
sudo chmod +x setup.sh
./setup.sh

# 2. Import data from GitHub
echo "📊 Importing data from GitHub..."
cd /opt/volunteer-map/backend
python scripts/import_github_data.py

# 3. Start backend service
echo "🔧 Starting backend service..."
sudo systemctl start volunteer-map
sudo systemctl enable volunteer-map
sudo systemctl status volunteer-map --no-pager -l

# 4. Set up Cloudflare Tunnel
echo "🔐 Setting up Cloudflare Tunnel..."
# Check if cloudflared is installed
if ! command -v cloudflared &> /dev/null; then
    echo "Installing cloudflared..."
    curl -fsSL https://pkg.cloudflare.com/cloudflare-signing-key.pub | sudo gpg --dearmor --out /usr/share/keyrings/cloudflare-archive-keyring.gpg
    echo "deb [signed-by=/usr/share/keyrings/cloudflare-archive-keyring.gpg] https://pkg.cloudflare.com/ $CF_DISTRO main" | sudo tee /etc/apt/sources.list.d/cloudflare-main.list
    sudo apt update
    sudo apt install cloudflared -y
fi

# 4. Create Cloudflare Tunnel (requires user interaction)
echo "⚠️  Creating Cloudflare Tunnel - this requires your input:"
cloudflared tunnel create volunteer-map

echo "✅ Deployment complete!"
echo ""
echo "Next steps:"
echo "1. Configure DNS in Cloudflare dashboard for volunteer.templeeearth.cc"
echo "2. Update cloudflare-tunnel-config.json with your Tunnel ID and Secret"
echo "3. Run: cloudflared tunnel --config /opt/volunteer-map/cloudflare-tunnel-config.json run"
echo "4. Visit http://volunteer.templeeearth.cc to verify"
echo ""
echo "To start the tunnel automatically, you can create a systemd service:"
echo "sudo nano /etc/systemd/system/cloudflare-tunnel.service"
echo "[Unit]"
echo "Description=Cloudflare Tunnel for volunteer.templeeearth.cc"
echo "After=network.target"
echo ""
echo "[Service]"
echo "Type=simple"
echo "User=your_username"
echo "WorkingDirectory=/opt/volunteer-map"
echo "ExecStart=/usr/bin/cloudflared tunnel --config /opt/volunteer-map/cloudflare-tunnel-config.json run"
echo "Restart=on-failure"
echo "RestartSec=5"
echo ""
echo "[Install]"
echo "WantedBy=multi-user.target"
echo ""
echo "Then: sudo systemctl daemon-reload && sudo systemctl enable cloudflare-tunnel && sudo systemctl start cloudflare-tunnel"
echo ""
echo "🎉 Deployment successful! Access your map at http://volunteer.templeeearth.cc"
