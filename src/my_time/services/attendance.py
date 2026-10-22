from ..models.leave import CorrectionRequest


def effective_times(db,attendance):
    correction=db.query(CorrectionRequest).filter_by(attendance_id=attendance.id,team_id=attendance.team_id,status="approved").order_by(CorrectionRequest.id.desc()).first()
    return {"effective_check_in_at":correction.check_in_at if correction else attendance.check_in_at,
            "effective_check_out_at":correction.check_out_at if correction else attendance.check_out_at,
            "corrected":correction is not None}
