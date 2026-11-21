# Same base image as the starter kit (the digest the organizers labeled every
# commit in). The runtime needs nothing beyond the Python standard library, and
# the fixture->test map is embedded inside selector.py, so this build context is
# a single file.
FROM python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90

WORKDIR /app
COPY selector.py /app/selector.py

CMD ["python", "/app/selector.py"]
