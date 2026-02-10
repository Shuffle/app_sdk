FROM python:3.14.2-alpine as base

# >3.10 has optimizations that break shared memory of variables
# IF you are updating the version of Python, it will need EXTENSIVE testing
#FROM python:3.11.3-alpine as base

FROM base as builder
RUN apk --no-cache add --update alpine-sdk libffi libffi-dev musl-dev openssl-dev tzdata coreutils

RUN mkdir /install
WORKDIR /install

FROM base

#--no-cache 
RUN apk update && apk add --update tzdata libmagic alpine-sdk libffi libffi-dev musl-dev openssl-dev coreutils

COPY --from=builder /install /usr/local
COPY requirements.txt /requirements.txt
RUN pip3 install -r /requirements.txt --verbose --progress-bar=off 

COPY shuffle_sdk/__init__.py /app/walkoff_app_sdk/__init__.py
COPY shuffle_sdk/shuffle_sdk.py /app/walkoff_app_sdk/app_base.py
