FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Download spaCy model required by Presidio at build time so it's baked into the image
RUN python -m spacy download en_core_web_sm

COPY . .

EXPOSE 9000

CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "9000"]
