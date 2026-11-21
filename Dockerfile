FROM minizinc/minizinc:2.10.0 AS minizinc

FROM node:22-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
COPY --from=minizinc /usr/local/bin/ /usr/local/bin/
COPY --from=minizinc /usr/local/share/minizinc /usr/local/share/minizinc
COPY --from=minizinc /usr/local/lib/ /usr/local/lib/
RUN minizinc --solvers | grep -i gecode
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ backend/
COPY data/ data/
COPY examples/ examples/
COPY check_contract.py ./
COPY --from=frontend /app/frontend/dist frontend/dist/
WORKDIR /app/backend
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
