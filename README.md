# Volunteer Organization Map

Interactive map for volunteer.templeeearth.cc showing organizations and their descriptions.

## Features

- Interactive map with organization markers
- Filtering by organization type, location, and volunteer opportunities
- Detailed organization profiles with descriptions
- Volunteer opportunity listings
- Responsive design
- RESTful API for integration

## Quick Start

### Prerequisites

- Python 3.9+
- Node.js (for frontend development)
- SQLite (included with Python)
- Cloudflare Tunnel (optional, for production deployment)

### Installation

1. Clone or download the project to your server:

```bash
sudo mkdir -p /opt/volunteer-map
cd /opt/volunteer-map
```

2. Run the setup script:

```bash
sudo chmod +x setup.sh
./setup.sh
```

3. Start the services:

```bash
# Backend (auto-started via systemd)
sudo systemctl start volunteer-map

# Frontend development server
cd frontend
npm start
```

4. Access the application:

- Frontend: http://localhost:3000
- API: http://localhost:8000
- API Documentation: http://localhost:8000/docs

## Project Structure

```
/opt/volunteer-map/
├── backend/           # FastAPI backend application
│   ├── app/           # Main application package
│   │   ├── models.py  # Database models
│   │   ├── schemas.py # Pydantic schemas
│   │   └── main.py    # FastAPI application
│   ├── scripts/       # Utility scripts
│   │   └── seed_db.py # Database seeding script
│   ├── alembic.ini    # Alembic migration configuration
│   ├── requirements.txt # Python dependencies
│   └── .env           # Environment configuration
├── frontend/          # React/Vanilla JS frontend
│   ├── css/           # Stylesheets
│   ├── js/            # JavaScript application
│   ├── index.html     # Main HTML file
│   └── package.json   # (Optional) Frontend dependencies
├── data/             # Data files and configuration
├── scripts/          # Additional scripts
├── cloudflare-tunnel-config.json # Cloudflare Tunnel configuration
├── setup.sh          # Setup script
└── README.md         # This file
```

## Backend API

### Organizations

- `GET /api/organizations/` - List all organizations (with filtering)
- `GET /api/organizations/{id}` - Get specific organization
- `POST /api/organizations/` - Create new organization (admin)
- `PUT /api/organizations/{id}` - Update organization (admin)
- `DELETE /api/organizations/{id}` - Delete organization (admin)

### Volunteer Opportunities

- `GET /api/opportunities/` - List all opportunities
- `GET /api/organizations/{id}/opportunities` - Get opportunities for organization
- `POST /api/opportunities/` - Create new opportunity (admin)

### Search

- `GET /api/organizations/nearby` - Find organizations near a location
  - Parameters: latitude, longitude, radius_km, limit

### Statistics

- `GET /api/statistics/` - Get application statistics
- `GET /api/health/` - Health check endpoint

## Database Schema

### Organizations Table

- `id` - Primary key
- `name` - Organization name
- `description` - Detailed description
- `organization_type` - Type (ecovillage, nonprofit, community-group, educational)
- `website` - Organization website
- `email` - Contact email
- `phone` - Contact phone
- `address` - Street address
- `city` - City
- `region` - State/Province/Region
- `country` - Country
- `postal_code` - Postal/ZIP code
- `latitude` - Geographic latitude
- `longitude` - Geographic longitude
- `location` - PostGIS geography point
- `volunteer_opportunities` - Boolean flag
- `accepting_volunteers` - Boolean flag
- `created_at` - Timestamp
- `last_updated` - Timestamp

### Volunteer Opportunities Table

- `id` - Primary key
- `organization_id` - Foreign key to organizations
- `title` - Opportunity title
- `description` - Detailed description
- `role` - Role/position
- `skills_needed` - Required skills
- `start_date` - Start date
- `end_date` - End date
- `commitment` - Time commitment
- `remote_options` - Remote work available
- `application_email` - Application contact email
- `created_at` - Timestamp

## Deployment

### Production with Cloudflare Tunnel

1. Install Cloudflare Tunnel:

```bash
cloudflared tunnel --url http://localhost:8000
```

2. Create and configure the tunnel:

```bash
cloudflared tunnel create volunteer-map
```

3. Update `/opt/volunteer-map/cloudflare-tunnel-config.json` with your account details.

4. Run the tunnel:

```bash
cloudflared tunnel --config /opt/volunteer-map/cloudflare-tunnel-config.json run
```

5. Configure your DNS to point `volunteer.templeeearth.cc` to the Cloudflare Tunnel.

### Systemd Service

The application includes a systemd service file (`/etc/systemd/system/volunteer-map.service`) that:

- Runs as the `terexitarius` user
- Automatically restarts on failure
- Starts on boot

Manage the service with:

```bash
sudo systemctl start volunteer-map
sudo systemctl stop volunteer-map
sudo systemctl restart volunteer-map
sudo systemctl status volunteer-map
```

## Development

### Backend Development

```bash
cd /opt/volunteer-map/backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend Development

```bash
cd /opt/volunteer-map/frontend
npm install
npm start
```

### Running Migrations

```bash
cd /opt/volunteer-map/backend
alembic upgrade head
```

## Data Management

### Seeding Sample Data

```bash
cd /opt/volunteer-map/backend
python scripts/seed_db.py
```

### Adding Organizations

Organizations can be added via the API or through a future admin interface.

## Configuration

### Environment Variables

- `DATABASE_URL` - Database connection string
- `SECRET_KEY` - Secret key for signing data
- `BACKEND_CORS_ORIGINS` - Allowed CORS origins

## Security Considerations

1. Change the `SECRET_KEY` in production.
2. Use HTTPS with Cloudflare Tunnel.
3. Implement proper authentication/authorization for API endpoints.
4. Regularly update dependencies for security patches.

## Troubleshooting

### Common Issues

**Database connection errors:**
- Ensure SQLite is installed
- Check file permissions for the database file

**API not responding:**
- Check systemd service status: `sudo systemctl status volunteer-map`
- Check logs: `journalctl -u volunteer-map`

**Frontend not loading:**
- Ensure Node.js and npm are installed
- Check that the backend API is running

### Debugging

Enable debug logging by setting `DEBUG=1` in the environment.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgments

- Thanks to the open-source tools that make this project possible
- Special thanks to the volunteer.templeeearth.cc team for the inspiration
