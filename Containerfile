FROM astral/uv:python3.14-alpine

WORKDIR /app

# Accept version from build argument (defaults to dev for local builds)
ARG VERSION=dev
ENV APP_VERSION=${VERSION}

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1

# Copy only dependency files first to leverage Docker caching
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project --no-dev

# Copy the rest of the application
COPY app/ ./app/
COPY static/ ./static/
COPY templates/ ./templates/

# Set up a directory for the persistent database
ENV DB_PATH=/app/data/camerasheet.db
RUN mkdir -p /app/data
VOLUME /app/data

# Expose port
EXPOSE 8000

# Health check: Verifies the server is up AND the database is reachable
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health').read()" || exit 1

# Run the application using the new module path
CMD [".venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
