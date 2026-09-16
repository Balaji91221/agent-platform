# Jenkins with the two plugins the platform needs, baked in so a fresh
# `docker compose up` has the three agent jobs already defined.
FROM jenkins/jenkins:lts-jdk21

USER root
# The jobs write the host entry with grep/sed; both are in the base image.
# curl is here so a job can smoke-test the deployed agent.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*
USER jenkins

RUN jenkins-plugin-cli --plugins \
      configuration-as-code \
      job-dsl \
      workflow-aggregator

# No setup wizard: the admin user comes from casc.yaml instead.
ENV JAVA_OPTS="-Djenkins.install.runSetupWizard=false"
ENV CASC_JENKINS_CONFIG=/var/jenkins_conf/casc.yaml
