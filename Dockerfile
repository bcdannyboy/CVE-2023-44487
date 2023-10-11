FROM alpine:latest
WORKDIR /work
COPY . /app
RUN apk update && apk add python3 py3-pip
RUN pip3 install -r /app/requirements.txt
ENTRYPOINT ["python3", "/app/cve202344487.py"]
