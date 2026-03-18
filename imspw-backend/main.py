from fastapi import FastAPI, Header, HTTPException, Depends, APIRouter
from app.core.config import settings
from app.schemas.webhook import WebhookPayload, WebhookResponse
import jwt
import base64
import logging

# Configure logging
logging.basicConfig(level=settings.LOG_LEVEL)
logger = logging.getLogger(__name__)

# Track recently processed messages to prevent reply loops
_processed_messages = {}

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

        # Check for image messages
        is_image = payload.media_type == "image" or bool(payload.media_url)
        image_url = payload.media_url if is_image else None
        
        logger.info(f"Received {'IMAGE' if is_image else 'TEXT'} from {payload.platform} ({payload.device_id}): {decoded_content if not is_image else image_url}")
        logger.debug(f"Full payload: {payload.model_dump()}")

        # Prevent reply loops: Check if this is a message we just sent (echo detection)
        # Only skip if it's the EXACT same message content within 30 seconds
        import time
        current_time = time.time()
        
        # Create a key based on the incoming message content
        msg_key = (
            payload.device_id, 
            payload.platform, 
            payload.chat.uuid if payload.chat else "", 
            decoded_content[:100]  # Use first 100 chars of content
        )
        
        if msg_key in _processed_messages:
            last_processed = _processed_messages[msg_key]
            # Only skip if processed within 30 seconds (shorter window)
            if current_time - last_processed < 30:
                logger.info(f"Skipping duplicate message (reply loop prevention): {decoded_content[:50]}")
                return WebhookResponse(status="ok")  # No reply
        _processed_messages[msg_key] = current_time
        
        # Clean old entries (keep cache small)
        for key in list(_processed_messages.keys()):
            if current_time - _processed_messages[key] > 60:
                del _processed_messages[key]

        # --- AUTO-REPLY LOGIC ---
        reply_text = "I received your message! (Auto-Reply Test)"
        reply_image = None  # Set to an image URL to auto-reply with image

        if payload.user_info and payload.user_info.username:
            reply_text = f"Hello {payload.user_info.username}, I received your {'IMAGE' if is_image else 'TEXT'} on {payload.platform}!"

        # Auto-reply with image for incoming images
        if is_image:
            # Option 1: Return an image URL (must be publicly accessible)
            reply_image = "https://cdn.pixabay.com/photo/2015/11/16/14/43/cat-1045782_640.jpg"
            reply_text = "Thanks for the image! Here's mine:"
            
            # Option 2: Just acknowledge the image
            # reply_text = f"Thanks for the image, {payload.user_info.username if payload.user_info and payload.user_info.username else 'friend'}! I received it on {payload.platform}."

        logger.info(f"Sending Auto-Reply: {reply_text} (Image: {reply_image})")

        return WebhookResponse(status="ok", message=reply_text, image=reply_image)
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
