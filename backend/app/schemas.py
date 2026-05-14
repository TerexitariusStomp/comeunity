from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List
from typing import Optional, List, Tuple

class OrganizationBase(BaseModel):
    name: str = Field(..., max_length=200)
    description: Optional[str] = Field(None, max_length=2000)
    organization_type: Optional[str] = Field(None, max_length=100)
    website: Optional[str] = Field(None, max_length=500)
    email: Optional[str] = Field(None, max_length=200)
    phone: Optional[str] = Field(None, max_length=50)
    address: Optional[str] = Field(None, max_length=500)
    city: Optional[str] = Field(None, max_length=100)
    region: Optional[str] = Field(None, max_length=100)
    country: Optional[str] = Field(None, max_length=100)
    postal_code: Optional[str] = Field(None, max_length=20)
    latitude: Optional[float]
    longitude: Optional[float]
    location: Optional[Tuple[float, float]]  # (latitude, longitude)
    source: str = Field(..., max_length=50)
    accepts_volunteers: bool = False
    accepts_visitors: bool = False
    accepts_shortterm: bool = False
    accepts_longterm: bool = False
    has_jobs: bool = False

class OrganizationCreate(OrganizationBase):
    pass

class OrganizationUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)
    organization_type: Optional[str] = Field(None, max_length=100)
    website: Optional[str] = Field(None, max_length=500)
    email: Optional[str] = Field(None, max_length=200)
    phone: Optional[str] = Field(None, max_length=50)
    address: Optional[str] = Field(None, max_length=500)
    city: Optional[str] = Field(None, max_length=100)
    region: Optional[str] = Field(None, max_length=100)
    country: Optional[str] = Field(None, max_length=100)
    postal_code: Optional[str] = Field(None, max_length=20)
    latitude: Optional[float]
    longitude: Optional[float]
    location: Optional[Tuple[float, float]]  # (latitude, longitude)
    source: Optional[str] = Field(None, max_length=50)
    accepts_volunteers: Optional[bool]
    accepts_visitors: Optional[bool]
    accepts_shortterm: Optional[bool]
    accepts_longterm: Optional[bool]
    has_jobs: Optional[bool]

class OrganizationResponse(OrganizationBase):
    id: int
    last_updated: Optional[datetime]
    created_at: Optional[datetime]
    
    class Config:
        from_attributes = True

class VolunteerOpportunityBase(BaseModel):
    organization_id: int
    title: str = Field(..., max_length=200)
    description: str = Field(..., max_length=2000)
    role: Optional[str] = Field(None, max_length=100)
    skills_needed: Optional[str] = Field(None, max_length=200)
    start_date: Optional[datetime]
    end_date: Optional[datetime]
    commitment: Optional[str] = Field(None, max_length=100)
    remote_options: bool = False
    application_email: Optional[str] = Field(None, max_length=200)

class VolunteerOpportunityCreate(VolunteerOpportunityBase):
    pass

class VolunteerOpportunityResponse(VolunteerOpportunityBase):
    id: int
    created_at: datetime
    
    class Config:
        from_attributes = True

class OrganizationWithOpportunities(OrganizationResponse):
    opportunities: List[VolunteerOpportunityResponse] = []
