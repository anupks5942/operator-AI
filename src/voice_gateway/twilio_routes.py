import os
from fastapi import APIRouter
from fastapi.responses import Response
from dotenv import load_dotenv

load_dotenv()
router = APIRouter()


VOICE_WS_URL = os.getenv("VOICE_WS_URL")
print(VOICE_WS_URL)

@router.get("/health")
async def health():
    return {
        "status": "healthy server",
        "service": "voice-gateway"
    }

@router.post("/voice")
async def voice():
    twiml = f"""
    <Response>
        <Connect>
            <ConversationRelay
                url="{VOICE_WS_URL}"
                welcomeGreeting="Hello, welcome to SpyderWash support. How can I help you today?"
            />
        </Connect>
    </Response>
    """

    return Response(
        content=twiml,
        media_type="application/xml",
    )
