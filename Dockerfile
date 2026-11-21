# Same pinned base image as the starter kit. The runtime is pure Python
# stdlib; every map both engines need is embedded inside selector.py itself,
# so the build context is a single file and nothing can go missing.
FROM python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90

WORKDIR /app
COPY selector.py /app/selector.py

CMD ["python", "/app/selector.py"]
