FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# BOX_ROLE est injecté au déploiement (voir deploy.sh), pas de valeur par défaut
CMD ["python", "main.py"]