# Base image
FROM python:3.9-alpine

# Token to authenticate to GH to download gh-bbs2gh extension
ARG GH_TOKEN
ENV GH_TOKEN=$GH_TOKEN

# Install required packages
RUN apk add \
  curl \
  gpg \
  unzip \
  icu-dev \
  jq \
  github-cli \
  gcompat \
  openssh-client \
  bash

RUN apk update

# Install all python module dependencies
WORKDIR /app
COPY requirements.txt /app
RUN pip3 install --no-cache-dir -r requirements.txt

# Install gh-bbs2gh extension
RUN gh extension install github/gh-bbs2gh
RUN gh extension upgrade github/gh-bbs2gh

# Unset the ENV
ENV GH_TOKEN=
