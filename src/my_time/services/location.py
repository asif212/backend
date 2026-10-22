import math
from sqlalchemy.orm import Session
from fastapi import HTTPException
from ..models.core import WorkLocation
from ..config import settings

def haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371000.0  # Earth radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi / 2.0) ** 2 + \
        math.cos(phi1) * math.cos(phi2) * \
        math.sin(delta_lambda / 2.0) ** 2
    
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def validate_location(db: Session, team_id: int, lat: float, lng: float, accuracy: float):
    if accuracy > settings.MAX_ACCURACY_M:
        raise HTTPException(
            status_code=400, 
            detail=f"Location accuracy ({accuracy}m) is worse than allowed ({settings.MAX_ACCURACY_M}m)"
        )

    locations = db.query(WorkLocation).filter(
        WorkLocation.team_id == team_id,
        WorkLocation.active == True
    ).all()

    if not locations:
        raise HTTPException(status_code=400, detail="Ask your lead to add a work location")

    valid_location_id = None
    min_distance = float('inf')

    for loc in locations:
        dist = haversine_distance_m(lat, lng, loc.lat, loc.lng)
        if dist <= settings.GEOFENCE_RADIUS_M and dist < min_distance:
            min_distance = dist
            valid_location_id = loc.id

    if valid_location_id is None:
        raise HTTPException(status_code=400, detail="You are not within an active work location")

    return valid_location_id, min_distance

