FROM python:3.11.3

WORKDIR /code

COPY ./requirements.txt /code/requirements.txt

RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

COPY . /code
COPY celery/.netrc /root

ENV PYTHONUNBUFFERED True
ENV PORT 8090

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port $PORT"]