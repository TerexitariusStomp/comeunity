from sqlalchemy import Column, Integer, String, Text, Float, DateTime, Boolean
from sqlalchemy.sql import func
from sqlalchemy.ext.declarative import declarative_base

import datetime

Base = declarative_base()

class Organization(Base):
    __tablename__ = 'organizations'
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text)
    organization_type = Column(String(100))
    popup_html = Column(Text)
    website = Column(String(500))
    email = Column(String(200))
    phone = Column(String(50))
    address = Column(String(500))
    city = Column(String(100))
    region = Column(String(100))
    country = Column(String(100))
    postal_code = Column(String(20))
    latitude = Column(Float)
    longitude = Column(Float)
    location = Column(String)
    source = Column(String(50))  # ecobasa, ecovillage, ic-directory, facebook
    accepts_volunteers = Column(Boolean, default=False)
    accepts_visitors = Column(Boolean, default=False)
    accepts_shortterm = Column(Boolean, default=False)
    accepts_longterm = Column(Boolean, default=False)
    has_jobs = Column(Boolean, default=False)
    last_updated = Column(DateTime(timezone=True), server_default=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'organization_type': self.organization_type,
            'website': self.website,
            'email': self.email,
            'phone': self.phone,
            'address': self.address,
            'city': self.city,
            'region': self.region,
            'country': self.country,
            'postal_code': self.postal_code,
            'latitude': self.latitude,
            'longitude': self.longitude,
            'source': self.source,
            'accepts_volunteers': self.accepts_volunteers,
            'accepts_visitors': self.accepts_visitors,
            'accepts_shortterm': self.accepts_shortterm,
            'accepts_longterm': self.accepts_longterm,
            'has_jobs': self.has_jobs,
            'last_updated': self.last_updated.isoformat() if self.last_updated else None,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

class VolunteerOpportunity(Base):
    __tablename__ = 'volunteer_opportunities'
    
    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, nullable=False)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=False)
    role = Column(String(100))
    skills_needed = Column(String(200))
    start_date = Column(DateTime(timezone=True))
    end_date = Column(DateTime(timezone=True))
    commitment = Column(String(100))
    remote_options = Column(Boolean, default=False)
    application_email = Column(String(200))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    def to_dict(self):
        return {
            'id': self.id,
            'organization_id': self.organization_id,
            'title': self.title,
            'description': self.description,
            'role': self.role,
            'skills_needed': self.skills_needed,
            'start_date': self.start_date.isoformat() if self.start_date else None,
            'end_date': self.end_date.isoformat() if self.end_date else None,
            'commitment': self.commitment,
            'remote_options': self.remote_options,
            'application_email': self.application_email,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
