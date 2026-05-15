FROM python:3.11-slim

# 1) Dépendances système
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc g++ \
    gdal-bin libgdal-dev \
    libspatialindex-dev \
    proj-bin proj-data libproj-dev \
    libgeos-dev \
    libpq-dev \
    libreoffice-writer \
    fonts-dejavu-core \
    ca-certificates curl \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app



# 3) Rend pip/requests plus calmes et utilise la trust store système
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

# 4) Copie un requirements UTF-8 dédié au build Docker.
COPY requirements.docker.txt ./requirements.docker.txt

# 5) Installe les deps Python.
#    - Pas d'upgrade pip (ça forcerait un accès à PyPI tout de suite).
#    - Ajout de --trusted-host aussi ici (plan B si ton CA n'est pas installé).
RUN pip install --no-cache-dir \
      --trusted-host pypi.org --trusted-host files.pythonhosted.org \
      -r requirements.docker.txt \
  && pip install --no-cache-dir \
      --trusted-host pypi.org --trusted-host files.pythonhosted.org \
      GeoAlchemy2==0.14.7 geopandas==0.14.4 shapely==2.0.5 pyproj==3.6.1 rtree==1.3.0 requests==2.32.3 gunicorn==22.0.0

# 6) Copie du code après l'install (meilleur cache Docker)
COPY . /app

EXPOSE 8000
CMD ["sh", "-c", "gunicorn -w 2 -b 0.0.0.0:${PORT:-8000} --timeout 0 --graceful-timeout 300 app_resilience:app"]
