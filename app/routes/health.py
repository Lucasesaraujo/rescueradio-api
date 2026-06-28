from fastapi import APIRouter, Request, Response

from app.infra.observability.metrics import render_metrics

router = APIRouter(tags=["Observabilidade"])


@router.get("/health")
def health(request: Request):
    udp_enabled = getattr(request.app.state, "udp_enabled", False)
    return {
        "status": "ok",
        "service": "rescueradio-api",
        "transports": ["http", "websocket"] + (["udp"] if udp_enabled else []),
    }


@router.get("/metrics")
def metrics():
    payload, content_type = render_metrics()
    return Response(content=payload, media_type=content_type)
