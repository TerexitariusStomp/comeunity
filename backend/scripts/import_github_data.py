import requests
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models import Base, Organization, VolunteerOpportunity
from app.main import SessionLocal
import datetime

def import_volunteer_map_data():
    db = SessionLocal()
    
    try:
        print("Fetching data from GitHub...")
        response = requests.get('https://raw.githubusercontent.com/TerexitariusStomp/volunteer-map/main/volunteer_map_data.json')
        response.raise_for_status()
        geo_data = response.json()
        
        # Determine data format
        if isinstance(geo_data, list):
            features = geo_data
        else:
            features = geo_data.get('features', [])
        
        # Clear existing data (for development)
        db.query(Organization).delete()
        db.commit()
        
        # Process each feature
        count = 0
        for feature in features:
            props = feature.get('properties', {})
            geometry = feature.get('geometry', {})
            
            # Create organization
            org = Organization(
                name=props.get('name', ''),
                description=props.get('popup', ''),
                organization_type=props.get('source', ''),
                website='',  # Extract from popup if needed
                email=None,
                phone=None,
                address=None,
                city=None,
                region=None,
                country=None,
                postal_code=None,
                latitude=geometry.get('coordinates', [0, 0])[1] if isinstance(geometry, dict) and 'coordinates' in geometry else None,
                longitude=geometry.get('coordinates', [0, 0])[0] if isinstance(geometry, dict) and 'coordinates' in geometry else None,
                location=None,  # We'll skip location for now since it's not essential
                source=props.get('source', ''),
                accepts_volunteers=props.get('acceptsVolunteers', False),
                accepts_visitors=props.get('acceptsVisitors', False),
                has_jobs=props.get('hasJobs', False),
                last_updated=None,
                created_at=None
            )
            
            db.add(org)
            count += 1
            
            if count % 100 == 0:
                db.commit()
                print(f"Added {count} organizations...")
        
        db.commit()
        print(f"Successfully imported {count} organizations from GitHub")
        
    except Exception as e:
        db.rollback()
        print(f"Error importing data: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    import_volunteer_map_data()
