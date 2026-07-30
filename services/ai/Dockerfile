FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt ./
# CPU 전용 torch wheel을 먼저 설치 — 일반 pip로 설치하면 GPU/CUDA 라이브러리까지
# 딸려와서 용량이 몇 배로 커짐. CPU 서버에는 이 wheel이 훨씬 가볍고 충분함.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir transformers tqdm

COPY src ./src

EXPOSE 8001

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8001"]