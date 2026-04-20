from fastapi import APIRouter, Request, status

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


@router.post("/twilio", status_code=status.HTTP_202_ACCEPTED)
async def twilio_webhook(request: Request) -> dict[str, str]:
    await request.body()
    return {"status": "accepted", "provider": "twilio"}


@router.post("/plivo", status_code=status.HTTP_202_ACCEPTED)
async def plivo_webhook(request: Request) -> dict[str, str]:
    await request.body()
    return {"status": "accepted", "provider": "plivo"}
