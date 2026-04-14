FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir fastapi uvicorn

RUN echo 'from fastapi import FastAPI\napp = FastAPI()\n@app.get("/")\ndef root():\n    return {"status": "ok"}' > main.py

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]