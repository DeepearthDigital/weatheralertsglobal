# Dockerfile
FROM python:3.9-slim

# Set the working directory in the container
WORKDIR /workspace

# Create a non-root user and group
RUN groupadd -r wag-user && useradd -r -g wag-user wag-user

# Copy the application code into the container
COPY . /workspace

# Install dependencies (you might need to adjust this depending on your project's requirements)
RUN pip install --no-cache-dir -r requirements.txt

# Install supervisord
RUN apt-get update && apt-get install -y supervisor

# Copy the supervisor config
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Change ownership of /workspace to the new user
RUN chown -R wag-user:wag-user /workspace
RUN chown -R wag-user:wag-user /etc/supervisor

# Switch to the non-root user
USER wag-user

# print all files in the directory, for debugging purposes
RUN ls -lha

# Set the entrypoint to supervisord
# Use -c flag to tell supervisor where to find the config file
ENTRYPOINT ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]