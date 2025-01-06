FROM python:3.9-slim as builder # Or your preferred base image

# Set the working directory in the container
WORKDIR /app

# Copy the application code into the container
COPY . /app

# Install dependencies (you might need to adjust this depending on your project's requirements)
RUN pip install --no-cache-dir -r requirements.txt

# Install supervisord
RUN apt-get update && apt-get install -y supervisor

# Copy the supervisor config
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# print all files in the directory, for debugging purposes
RUN ls -lha

# Set the entrypoint to supervisord
ENTRYPOINT ["/usr/bin/supervisord", "-n"]