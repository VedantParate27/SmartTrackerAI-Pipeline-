@echo off
echo Starting SmartTracker AI Backend with HTTPS on port 8000...

if exist "local-cert.pem" (
    uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload --ssl-keyfile local-key.pem --ssl-certfile local-cert.pem
) else (
    uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload --ssl-keyfile certs/key.pem --ssl-certfile certs/cert.pem
)
