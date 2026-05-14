# Deployment Guide: volunteer.templeeearth.cc

## Prerequisites

1. **Cloudflare Account**: You need a Cloudflare account with access to the templeeearth.cc domain.
2. **Domain Configuration**: The domain volunteer.templeeearth.cc should be added to your Cloudflare account.
3. **Server Access**: You need SSH access to the server at 100.77.190.37.

## Step-by-Step Deployment

### 1. Install Dependencies

```bash
cd /opt/volunteer-map
sudo chmod +x setup.sh
./setup.sh
```

### 2. Configure Database

```bash
cd /opt/volunteer-map/backend
alembic upgrade head
python scripts/import_github_data.py
```

### 3. Set Up Cloudflare Tunnel

#### Install cloudflared:
```bash
# Add Cloudflare repository
curl -fsSL https://pkg.cloudflare.com/cloudflare-signing-key.pub | sudo gpg --dearmor --out /usr/share/keyrings/cloudflare-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/cloudflare-archive-keyring.gpg] https://pkg.cloudflare.com/ $CF_DISTRO main" | sudo tee /etc/apt/sources.list.d/cloudflare-main.list
sudo apt update
sudo apt install cloudflared -y
```

#### Authenticate with Cloudflare:
```bash
cloudflared tunnel --accept-tos --signup
```

This will open a browser window to authenticate with Cloudflare. Follow the prompts.

#### Create the tunnel:
```bash
cloudflared tunnel create volunteer-map
```

This will output a Tunnel ID and Tunnel Secret. Save these in a safe place.

#### Configure the tunnel:
Update `/opt/volunteer-map/cloudflare-tunnel-config.json` with:
- Your Account Tag (from Cloudflare dashboard)
- Tunnel ID from the create command
- Tunnel Secret from the create command

#### Run the tunnel:
```bash
cloudflared tunnel --config /opt/volunteer-map/cloudflare-tunnel-config.json run
```

### 4. Configure DNS

1. Go to your Cloudflare dashboard
2. Navigate to DNS → Records
3. Create an A record for `volunteer.templeeearth.cc` that points to the Cloudflare Tunnel

### 5. Start the Services

```bash
# Start the backend API
sudo systemctl start volunteer-map

# Start the Cloudflare Tunnel (if not running as a service)
cloudflared tunnel --config /opt/volunteer-map/cloudflare-tunnel-config.json run
```

### 6. Verify Deployment

1. Visit http://volunteer.templeeearth.cc
2. The map should load with all 1,964 organizations
3. Check that filtering works correctly

## Troubleshooting

### Common Issues

**"502 Bad Gateway" error:**
- Check that the backend API is running: `sudo systemctl status volunteer-map`
- Check logs: `journalctl -u volunteer-map`

**Tunnel not connecting:**
- Verify Cloudflare authentication
- Check tunnel configuration file
- Ensure the correct port (8000) is specified

**Data not loading:**
- Check that the import script ran successfully
- Verify database connection

### Useful Commands

```bash
# Check service status
sudo systemctl status volunteer-map

# View logs
journalctl -u volunteer-map -f

# Restart service
sudo systemctl restart volunteer-map

# Check if cloudflared tunnel is running
ps aux | grep cloudflared
```

## Maintenance

### Updating Data

When the GitHub repository updates with new data:

```bash
cd /opt/volunteer-map/backend
python scripts/import_github_data.py
sudo systemctl restart volunteer-map
```

### Updating the Application

```bash
cd /opt/volunteer-map
git pull origin main
sudo systemctl restart volunteer-map
```

## Security Considerations

1. **Change default secrets**: Update the SECRET_KEY in `.env`
2. **Use HTTPS**: Cloudflare Tunnel provides HTTPS automatically
3. **Regular updates**: Keep dependencies updated for security patches
4. **Backup database**: Regularly backup the SQLite database

## Support

If you encounter issues, check:
- Cloudflare Tunnel documentation: https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/
- FastAPI deployment guide: https://fastapi.tiangolo.com/deployment/
- Contact support if needed.

---

**The application is now deployed and accessible at http://volunteer.templeeearth.cc**
