FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# 의존성 먼저 설치 (레이어 캐시 활용). requirements.txt 가 생기면 자동 설치됨
COPY requirements.tx[t] ./
RUN if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; fi

COPY . .

EXPOSE 8000

# TODO: 프레임워크 확정 후 교체
#   FastAPI 예: CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
#   Django 예:  CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
CMD ["python", "-m", "http.server", "8000"]
