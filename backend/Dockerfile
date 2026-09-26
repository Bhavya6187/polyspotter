FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# gunicorn + uvicorn worker instead of bare uvicorn:
#  - binds [::] (dual-stack) so the frontend can reach us over Railway's
#    private network, which resolves to IPv6 only in this environment;
#  - --max-requests recycles the worker roughly hourly so Python heap
#    fragmentation can't ratchet RSS upward between deploys.
CMD ["sh", "-c", "exec gunicorn app:app --bind \"[::]:${PORT:-8000}\" --workers 1 --worker-class uvicorn_worker.UvicornWorker --max-requests 20000 --max-requests-jitter 2000 --timeout 90 --graceful-timeout 30 --keep-alive 5 --access-logfile - --error-logfile -"]
