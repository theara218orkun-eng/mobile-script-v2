# IMSPW Backend

This is the backend server for the [IMSPW Script](https://github.com/your-repo/imspw-script). It receives intercepted messages via a webhook, processes them, and can send optional auto-replies.

## Features

- **Webhook Endpoint:** `/api/webhook` to receive messages.
- **JWT Authentication:** Secures the endpoint using `PROCESSOR_API_SECRET`.
- **Payload Parsing:** Decodes Base64 message content.
- **Extensible:** Ready for adding database storage or complex auto-reply logic.

## Setup

1.  **Clone the repository:**
    ```bash
    git clone <your-repo-url>
    cd imspw-backend
    ```

2.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

3.  **Configure Environment:**
    Copy `.env.example` to `.env` and set your secret key.
    ```bash
    cp .env.example .env
    ```
    *Note: The `PROCESSOR_API_SECRET` must match the one used in your `imspw-script` configuration.*

4.  **Run the Server:**
    ```bash
    uvicorn main:app --reload
    ```

## Docker

You can also run the backend using Docker:

```bash
docker build -t imspw-backend .
docker run -p 8000:8000 --env-file .env imspw-backend
```

## API Endpoints

-   `POST /api/webhook`: Main endpoint for receiving messages.
-   `GET /health`: Health check endpoint.
