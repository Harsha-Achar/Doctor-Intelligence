"""HTTP routes for patient analytics. Mounted at /api/patients."""

from __future__ import annotations

from fastapi import APIRouter, File, Form, Query, UploadFile

from app.patients import service

router = APIRouter(tags=["patients"])


@router.get("/overview")
def overview():
    return service.overview()


@router.get("/mapping")
def mapping():
    return service.mapping()


@router.get("/mapping/{layer}")
def mapping_layer(layer: str):
    return service.mapping_records(layer)


@router.get("/sources")
def sources():
    return service.sources()


@router.get("/files/{file_id}")
def file_detail(file_id: int):
    return service.file_detail(file_id)


@router.get("/runs")
def runs():
    return service.runs()


@router.get("/runs/{run_id}")
def run_detail(run_id: int):
    return service.run_detail(run_id)


@router.post("/reprocess")
def reprocess():
    return service.reprocess()


@router.post("/upload")
async def upload(source: str = Form(...), file: UploadFile = File(...)):
    payload = await file.read()
    return service.preview_upload(source, file.filename or "upload.csv", payload)


@router.post("/upload/{upload_id}/process")
def process_upload(upload_id: str):
    return service.process_upload(upload_id)


@router.get("")
def patients(
    status: str | None = None,
    switched: bool | None = None,
    pending: bool | None = None,
    q: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
):
    return service.list_patients(status=status, switched=switched, pending=pending, q=q, page=page, page_size=page_size)


@router.get("/analytics")
def analytics(brand: str | None = None, payer: str | None = None):
    return service.journey_analytics(brand=brand, payer=payer)


@router.get("/privacy")
def privacy():
    return service.privacy()


@router.get("/evaluate")
def evaluate():
    return service.evaluation()


@router.get("/review")
def review_queue(source: str | None = None):
    return service.review_queue(source=source)


@router.get("/review/{review_id}")
def review_detail(review_id: int):
    return service.review_detail(review_id)


@router.post("/review/{review_id}/assign")
def review_assign(review_id: int, body: dict):
    return service.assign_review(review_id, str(body.get("daiichi_patient_id") or ""))


@router.post("/review/{review_id}/new")
def review_new(review_id: int):
    return service.new_patient_review(review_id)


@router.post("/review/{review_id}/defer")
def review_defer(review_id: int):
    return service.defer_review(review_id)


@router.post("/review/{review_id}/undo")
def review_undo(review_id: int):
    return service.undo_review(review_id)


@router.get("/records/{ref}")
def record_detail(ref: str):
    return service.record_detail(ref)


@router.get("/{patient_id}")
def patient(patient_id: str):
    return service.patient_detail(patient_id)


@router.get("/{patient_id}/timeline")
def timeline(patient_id: str):
    return service.patient_timeline(patient_id)


@router.get("/{patient_id}/doses")
def doses(patient_id: str):
    return service.patient_doses(patient_id)


@router.get("/{patient_id}/records")
def records(patient_id: str):
    return service.patient_records(patient_id)


@router.get("/{patient_id}/history")
def history(patient_id: str):
    return service.patient_history(patient_id)
