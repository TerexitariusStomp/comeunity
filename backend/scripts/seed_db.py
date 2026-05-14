import os
import sys
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models import Base, Organization, VolunteerOpportunity

# Add project directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import SessionLocal

def seed_database():
    """Seed the database with sample organizations."""
    db = SessionLocal()
    
    try:
        # Clear existing data (for development purposes)
        db.query(Organization).delete()
        db.query(VolunteerOpportunity).delete()
        
        # Sample organizations
        sample_orgs = [
{
                'name': 'Green Earth Ecovillage',
                'description': 'Sustainable ecovillage focused on permaculture and community living. We host volunteers year-round for organic farming and natural building projects.',
                'organization_type': 'ecovillage',
                'website': 'https://greenearth.example.com',
                'email': 'info@greenearth.example.com',
                'phone': '+123****7890',
                'address': '123 Green Valley Road',
                'city': 'EcoCity',
                'region': 'GreenState',
                'country': 'USA',
                'postal_code': '12345',
                'latitude': 37.7749,
                'longitude': -122.4194,
                'accepts_volunteers': True,
                'accepts_visitors': True,
                'has_jobs': False
            },
{
                'name': 'Community Helpers Nonprofit',
                'description': 'Nonprofit organization providing education and resources to underserved communities. We need volunteers for teaching, construction, and healthcare projects.',
                'organization_type': 'nonprofit',
                'website': 'https://communityhelpers.example.com',
                'email': 'volunteer@communityhelpers.example.com',
                'phone': '+0987654321',
                'address': '456 Community Lane',
                'city': 'HelpingTown',
                'region': 'CareState',
                'country': 'USA',
                'postal_code': '67890',
                'latitude': 40.7128,
                'longitude': -74.0060,
                'accepts_volunteers': True,
                'accepts_visitors': True,
                'has_jobs': False
            },
            {
                'name': 'Educational Earth Center',
                'description': 'Center for environmental education and sustainable living. We offer workshops, courses, and volunteer programs in organic gardening, renewable energy, and eco-construction.',
                'organization_type': 'educational',
                'website': 'https://earthcenter.example.com',
                'email': 'info@earthcenter.example.com',
                'phone': '+112****4455',
                'address': '789 Learning Way',
                'city': 'KnowledgeCity',
                'region': 'EduState',
                'country': 'USA',
                'postal_code': '11223',
                'latitude': 34.0522,
                'longitude': -118.2437,
                'accepts_volunteers': True,
                'accepts_visitors': True,
                'has_jobs': False
            },
            {
                'name': 'Community Garden Collective',
                'description': 'Urban community garden project bringing fresh produce to city neighborhoods. Volunteers needed for gardening, distribution, and community outreach.',
                'organization_type': 'community-group',
                'website': 'https://communitygarden.example.com',
                'email': 'garden@communitygarden.example.com',
                'phone': '+556****8899',
                'address': '321 Green Street',
                'city': 'Metropolis',
                'region': 'UrbanState',
                'country': 'USA',
                'postal_code': '99887',
                'latitude': 51.5074,
                'longitude': -0.1278,
                'accepts_volunteers': True,
                'accepts_visitors': True,
                'has_jobs': False
            },
            {
                'name': 'Wildlife Rescue Center',
                'description': 'Wildlife rehabilitation and rescue center. We care for injured and orphaned wild animals and release them back into their natural habitat.',
                'organization_type': 'nonprofit',
                'website': 'https://wildliferescue.example.com',
                'email': 'rescue@wildliferescue.example.com',
                'phone': '+998****6655',
                'address': '654 Forest Road',
                'city': 'NatureVille',
                'region': 'WildState',
                'country': 'USA',
                'postal_code': '44556',
                'latitude': 48.8566,
                'longitude': 2.3522,
                'accepts_volunteers': True,
                'accepts_visitors': True,
                'has_jobs': False
            }
        ]
        
        # Add sample organizations
        for org_data in sample_orgs:
            org = Organization(**org_data)
            db.add(org)
        
        db.commit()
        print(f"Successfully added {len(sample_orgs)} sample organizations")
        
        # Add sample volunteer opportunities
        opportunities = [
            {
                'organization_id': 1,
                'title': 'Organic Farming Volunteer',
                'description': 'Help with planting, weeding, harvesting, and maintaining our organic gardens. No experience required, training provided.',
                'role': 'Farm Volunteer',
                'skills_needed': 'Willingness to learn, physical stamina',
                'start_date': None,
                'end_date': None,
                'commitment': 'flexible',
                'remote_options': False,
                'application_email': 'info@greenearth.example.com'
            },
            {
                'organization_id': 2,
                'title': 'English Teacher Volunteer',
                'description': 'Teach English to children and adults in underserved communities. TEFL certification preferred but not required.',
                'role': 'Teacher',
                'skills_needed': 'Teaching skills, patience, communication',
                'start_date': None,
                'end_date': None,
                'commitment': '3-6 months',
                'remote_options': False,
                'application_email': 'volunteer@communityhelpers.example.com'
            }
        ]
        
        for opp_data in opportunities:
            opportunity = VolunteerOpportunity(**opp_data)
            db.add(opportunity)
        
        db.commit()
        print(f"Added {len(opportunities)} volunteer opportunities")
        
    except Exception as e:
        db.rollback()
        print(f"Error seeding database: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    seed_database()
