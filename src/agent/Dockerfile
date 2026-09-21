FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --require-hashes -r requirements.txt \
    && useradd --uid 10001 --create-home agent
COPY --chown=10001:10001 contracts.py retrieval.py main.py certificate_team.py ./
COPY --chown=10001:10001 evidence_team.py evidence_toolbox.py evidence_transport.py evidence_dispatch.py ./
USER 10001
EXPOSE 8088
CMD ["python", "main.py"]
