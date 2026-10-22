FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /opt/iges
RUN groupadd --system iges && useradd --system --gid iges iges
COPY requirements.txt /opt/iges/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY app /opt/iges/app
COPY db/migrations /opt/iges/db/migrations
USER iges
EXPOSE 8000
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000","--workers","2","--no-access-log"]
