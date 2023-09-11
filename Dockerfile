FROM datadog/agent:7

# disable autoconfigured checks; DD container checks
# do not work as-is on Render since there's no access
# to Kubelet/kube-state-metrics.
ENV DD_AUTOCONFIG_FROM_ENVIRONMENT=false

ENV NON_LOCAL_TRAFFIC=true
ENV DD_LOGS_STDOUT=yes

ENV DD_APM_ENABLED=true
ENV DD_APM_NON_LOCAL_TRAFFIC=true

ENV DD_DOGSTATSD_NON_LOCAL_TRAFFIC=true
ENV DD_PROCESS_AGENT_ENABLED=true

# Automatically set by Render
ARG RENDER_SERVICE_NAME=datadog

ENV DD_BIND_HOST=$RENDER_SERVICE_NAME
ENV DD_HOSTNAME=$RENDER_SERVICE_NAME

# Copy the custom conf.d files
# COPY ./conf.d /build_conf.d
# RUN cp -R /build_conf.d/* /etc/datadog-agent/conf.d/ && rm -rf /build_conf.d/

# Copy the secret conf.d files
COPY ./copy_secret_conf.sh /copy_secret_conf.sh
COPY conf.d_* /secret_configs/
RUN /copy_secret_conf.sh
