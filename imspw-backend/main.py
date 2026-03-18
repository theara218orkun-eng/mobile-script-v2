from fastapi import FastAPI, Header, HTTPException, Depends, APIRouter
from app.core.config import settings
from app.schemas.webhook import WebhookPayload, WebhookResponse
import jwt
import base64
import logging

# Configure logging
logging.basicConfig(level=settings.LOG_LEVEL)
logger = logging.getLogger(__name__)

app = FastAPI(title="IMSPW Backend")

async def verify_token(authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header missing")
    
    try:
        scheme, token = authorization.split()
        if scheme.lower() != 'bearer':
             raise HTTPException(status_code=401, detail="Invalid authentication scheme")
             
        jwt.decode(token, settings.PROCESSOR_API_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
    except Exception as e:
        logger.error(f"Token verification failed: {e}")
        raise HTTPException(status_code=401, detail="Could not validate credentials")

@app.post("/api/webhook", response_model=WebhookResponse)
async def webhook(payload: WebhookPayload, _ = Depends(verify_token)):
    """
    Receives messages from the IMSPW script.
    """
    try:
        # Decode content (just for logging/processing)
        decoded_content = "Cannot decode"
        try:
            if payload.content:
                decoded_content = base64.b64decode(payload.content).decode('utf-8')
        except Exception:
            pass

        logger.info(f"Received message from {payload.platform} ({payload.device_id}): {decoded_content}")
        logger.debug(f"Full payload: {payload.model_dump()}")

        # --- TEST AUTO-REPLY LOGIC ---
        reply_text = "I received your message! (Auto-Reply Test)"
        
        if payload.user_info and payload.user_info.username:
            reply_text = f"Hello {payload.user_info.username}, {reply_text}"
            
        logger.info(f"Sending Auto-Reply: {reply_text}")
        
        return WebhookResponse(status="ok", message=reply_text)
        # -----------------------------

    except Exception as e:
        logger.error(f"Error processing webhook: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/health")
def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
