import os, html, re
from fastapi import FastAPI, HTTPException, Depends, Query
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
import datetime
import uvicorn

from sqlalchemy import create_engine, func, select, and_, Column, Integer, String, Text, Float, DateTime, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from typing import Optional, List
import datetime
import uvicorn

# Import models and schemas
from app.models import Base, Organization, VolunteerOpportunity
from app.schemas import OrganizationCreate, OrganizationUpdate, OrganizationResponse, VolunteerOpportunityCreate, VolunteerOpportunityResponse, OrganizationWithOpportunities

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Database setup
DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite+pysqlite:////opt/volunteer-map/backend/organizations.db?check_same_thread=false')
engine = create_engine(DATABASE_URL, echo=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create tables
Base.metadata.create_all(bind=engine)

# Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Initialize FastAPI app
app = FastAPI(title="Volunteer Map HTTP Server", version="1.0.0", redirect_slashes=True)

from fastapi.middleware.cors import CORSMiddleware

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# Popup generation function
def generate_popup(org):
    parts = ['<b>' + html.escape(org.name) + '</b><br>']
    # Full-length description with scrollable container (up to 3000 chars)
    if org.description and len(org.description) > 10:
        desc = html.escape(org.description)
        parts.append('<div style="max-height:200px;overflow-y:auto;margin:4px 0;line-height:1.4;font-size:12px;">' + desc + '</div>')
    badges = []
    if org.accepts_volunteers:
        badges.append('<span style="background:#ffc107;color:black;padding:2px 6px;border-radius:3px;margin:1px;">Volunteer</span>')
    if org.accepts_visitors:
        if org.accepts_shortterm:
            badges.append('<span style="background:#17a2b8;color:white;padding:2px 6px;border-radius:3px;margin:1px;">Short-term</span>')
        if org.accepts_longterm:
            badges.append('<span style="background:#17a2b8;color:white;padding:2px 6px;border-radius:3px;margin:1px;">Long-term</span>')
    else:
        # If visitors overall is false but short/long are true somehow, don't show them (consistency)
        pass
    if org.has_jobs:
        badges.append('<span style="background:#dc3545;color:white;padding:2px 6px;border-radius:3px;margin:1px;">Jobs</span>')
    if badges:
        parts.append(' '.join(badges) + '<br>')
    lines = []
    if org.website:
        lines.append('<a href="' + html.escape(org.website) + '" target="_blank">Website</a>')
    if org.email:
        lines.append('<a href="mailto:' + html.escape(org.email) + '">Email</a>')
    if org.phone:
        lines.append(html.escape(org.phone))
    if lines:
        parts.append(' | '.join(lines))
    return ' '.join(parts)

# CRUD Operations for Organizations
@app.post('/api/organizations/', response_model=OrganizationResponse, status_code=201)
async def create_organization(organization: OrganizationCreate, db: Session = Depends(get_db)):
    db_org = Organization(**organization.dict())
    db.add(db_org)
    db.commit()
    db.refresh(db_org)
    return db_org

@app.get('/api/organizations/', response_model=List[OrganizationResponse])
async def read_organizations(
    skip: int = 0,
    limit: int = 100,
    source: Optional[str] = None,
    accepts_volunteers: Optional[bool] = None,
    accepts_visitors: Optional[bool] = None,
    accepts_shortterm: Optional[bool] = None,
    accepts_longterm: Optional[bool] = None,
    has_jobs: Optional[bool] = None,
    db: Session = Depends(get_db)
):
    query = db.query(Organization)
    if source:
        query = query.filter(Organization.source == source)
    if accepts_volunteers is not None:
        query = query.filter(Organization.accepts_volunteers == accepts_volunteers)
    if accepts_visitors is not None:
        query = query.filter(Organization.accepts_visitors == accepts_visitors)
    if accepts_shortterm is not None:
        query = query.filter(Organization.accepts_shortterm == accepts_shortterm)
    if accepts_longterm is not None:
        query = query.filter(Organization.accepts_longterm == accepts_longterm)
    if has_jobs is not None:
        query = query.filter(Organization.has_jobs == has_jobs)
    organizations = query.offset(skip).limit(limit).all()
    return organizations

# GeoJSON Endpoint - MUST be before {organization_id} route
# GeoJSON Endpoint
@app.get('/api/organizations/geojson/')
async def organizations_geojson(
    source: Optional[str] = None,
    accepts_volunteers: Optional[bool] = None,
    accepts_visitors: Optional[bool] = None,
    accepts_shortterm: Optional[bool] = None,
    accepts_longterm: Optional[bool] = None,
    has_jobs: Optional[bool] = None,
    db: Session = Depends(get_db)
):
    query = db.query(Organization)
    if source:
        query = query.filter(Organization.source == source)
    if accepts_volunteers is not None:
        query = query.filter(Organization.accepts_volunteers == accepts_volunteers)
    if accepts_visitors is not None:
        query = query.filter(Organization.accepts_visitors == accepts_visitors)
    if accepts_shortterm is not None:
        query = query.filter(Organization.accepts_shortterm == accepts_shortterm)
    if accepts_longterm is not None:
        query = query.filter(Organization.accepts_longterm == accepts_longterm)
    if has_jobs is not None:
        query = query.filter(Organization.has_jobs == has_jobs)
    
    organizations = query.all()
    
    features = []
    for org in organizations:
        if org.latitude and org.longitude:
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [org.longitude, org.latitude]
                },
                "properties": {
                    "id": org.id,
                    "name": org.name,
                    "description": org.description or "",
                    "popup": org.popup_html if org.popup_html else generate_popup(org),
                    "source": org.source,
                    "country": org.country or "",
                    "website": org.website or "",
                    "acceptsVolunteers": org.accepts_volunteers,
                    "acceptsVisitors": org.accepts_visitors,
                    "acceptsShortterm": org.accepts_shortterm,
                    "acceptsLongterm": org.accepts_longterm,
                    "hasJobs": org.has_jobs
                }
            })
    
    return JSONResponse({
        "type": "FeatureCollection",
        "features": features
    })


@app.get('/api/organizations/{organization_id}', response_model=OrganizationResponse)
async def read_organization(organization_id: int, db: Session = Depends(get_db)):
    db_org = db.query(Organization).filter(Organization.id == organization_id).first()
    if db_org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return db_org

@app.put('/api/organizations/{organization_id}', response_model=OrganizationResponse)
async def update_organization(
    organization_id: int, 
    organization: OrganizationUpdate, 
    db: Session = Depends(get_db)
):
    db_org = db.query(Organization).filter(Organization.id == organization_id).first()
    if db_org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    
    update_data = organization.dict(exclude_unset=True)
    for field, value in update_data.items():
        if value is not None:
            setattr(db_org, field, value)
    
    db.commit()
    db.refresh(db_org)
    return db_org

@app.delete('/api/organizations/{organization_id}', status_code=204)
async def delete_organization(organization_id: int, db: Session = Depends(get_db)):
    db_org = db.query(Organization).filter(Organization.id == organization_id).first()
    if db_org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    
    db.delete(db_org)
    db.commit()
    return None

# Volunteer Opportunities Endpoints
@app.post('/api/opportunities/', response_model=VolunteerOpportunityResponse, status_code=201)
async def create_opportunity(opportunity: VolunteerOpportunityCreate, db: Session = Depends(get_db)):
    db_org = db.query(Organization).filter(Organization.id == opportunity.organization_id).first()
    if db_org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    
    db_opportunity = VolunteerOpportunity(**opportunity.dict())
    db.add(db_opportunity)
    db.commit()
    db.refresh(db_opportunity)
    
    db_org.volunteer_opportunities = True
    db.commit()
    
    return db_opportunity

@app.get('/api/opportunities/', response_model=List[VolunteerOpportunityResponse])
async def read_opportunities(
    organization_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    query = db.query(VolunteerOpportunity)
    
    if organization_id:
        query = query.filter(VolunteerOpportunity.organization_id == organization_id)
    
    opportunities = query.offset(skip).limit(limit).all()
    return opportunities

@app.get('/api/organizations/{organization_id}/opportunities', response_model=OrganizationWithOpportunities)
async def read_organization_with_opportunities(organization_id: int, db: Session = Depends(get_db)):
    organization = db.query(Organization).filter(Organization.id == organization_id).first()
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    
    opportunities = db.query(VolunteerOpportunity).filter(
        VolunteerOpportunity.organization_id == organization_id
    ).all()
    
    return OrganizationWithOpportunities.from_orm(organization, opportunities=opportunities)


# Statistics Endpoint
@app.get('/api/statistics/')
async def get_statistics(db: Session = Depends(get_db)):
    total_organizations = db.query(Organization).count()
    total_opportunities = db.query(VolunteerOpportunity).count()
    
    source_counts = db.query(
        Organization.source,
        func.count(Organization.id)
    ).group_by(Organization.source).all()
    
    country_counts = db.query(
        Organization.country,
        func.count(Organization.id)
    ).group_by(Organization.country).all()
    
    volunteer_counts = db.query(
        func.count(Organization.id)
    ).filter(Organization.accepts_volunteers == True).scalar()
    
    visitor_counts = db.query(
        func.count(Organization.id)
    ).filter(Organization.accepts_visitors == True).scalar()
    
    jobs_counts = db.query(
        func.count(Organization.id)
    ).filter(Organization.has_jobs == True).scalar()
    
    return {
        'total_organizations': total_organizations,
        'total_opportunities': total_opportunities,
        'by_source': dict(source_counts),
        'by_country': dict(country_counts or {}),
        'feature_counts': {
            'accepts_volunteers': volunteer_counts or 0,
            'accepts_visitors': visitor_counts or 0,
            'accepts_shortterm': shortterm_counts or 0,
            'accepts_longterm': longterm_counts or 0,
            'has_jobs': jobs_counts or 0
        }
    }

@app.get('/api/healthz')
async def health_check():
    return {'status': 'healthy', 'service': 'volunteer-map', 'version': '1.0.0'}

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'frontend')

@app.get('/')
async def root():
    index_path = os.path.join(FRONTEND_DIR, 'index.html')
    with open(index_path, 'r') as f:
        return HTMLResponse(content=f.read())

@app.get('/css/{file_path:path}')
async def serve_css(file_path: str):
    css_path = os.path.join(FRONTEND_DIR, 'css', file_path)
    if os.path.exists(css_path):
        resp = FileResponse(css_path)
        resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
        return resp
    return HTMLResponse("", status_code=404)

@app.get('/js/{file_path:path}')
async def serve_js(file_path: str):
    js_path = os.path.join(FRONTEND_DIR, 'js', file_path)
    if os.path.exists(js_path):
        resp = FileResponse(js_path)
        resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
        return resp
    return HTMLResponse("", status_code=404)

@app.get('/api-info/')
async def api_info():
    return {
        'message': 'Volunteer Map HTTP Server',
        'version': '1.0.0',
        'endpoints': {
            'organizations': {
                'list': 'GET /api/organizations/',
                'geojson': 'GET /api/organizations/geojson',
                'read': 'GET /api/organizations/{id}',
                'create': 'POST /api/organizations/',
                'update': 'PUT /api/organizations/{id}',
                'delete': 'DELETE /api/organizations/{id}'
            },
            'opportunities': {
                'list': 'GET /api/opportunities/',
                'by_organization': 'GET /api/organizations/{id}/opportunities'
            },
            'search': {
                'nearby': 'GET /api/organizations/nearby'
            },
            'stats': 'GET /api/statistics/'
        }
    }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
