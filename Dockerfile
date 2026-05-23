FROM python:3.9-slim

WORKDIR /app

RUN pip install --no-cache-dir pipenv

COPY Pipfile ./
RUN pipenv install --system --skip-lock

COPY . .

CMD ["python", "main.py"]
