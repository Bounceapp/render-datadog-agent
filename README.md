# Datadog Agent for Render

Datadog helps you capture application traces and metrics that can help you improve the performance for your app.

You can set up a single Datadog agent to capture data for any number of services in your Render account.

This example deploys Datadog's [Docker agent](https://docs.datadoghq.com/agent/docker/) as a [private service](https://render.com/docs/private-services) on Render. Once deployed, you can start sending [APM/Distributed Tracing](https://docs.datadoghq.com/tracing/) and [DogStatsD](https://docs.datadoghq.com/developers/dogstatsd/?tab=hostagent) metrics to your private service URL.

The URL will look like `datadog-agent-lkyz` with APM available on TCP port `8126` and DogStatsD on UDP port `8125`.

> You will need to configure your Datadog API key by setting the `DD_API_KEY` environment variable to your private service.

## Custom configurations

You can create a secret file in render with the following name pattern `conf.d_<integration_name>_<file_name.yaml?` and this will be copied to its respective location in the container `/etc/datadog-agent/conf.d/<integration_name>/<file_name>`.

*Example:* `conf.d_postgres.d_conf.yaml` will be copied to `/etc/datadog-agent/conf.d/postgres.d/conf.yaml`

### Database monitoring

Create a secret file in Render named `conf.d_postgres.d_conf.yaml` and content:
  
  ```yaml
  init_config:
  instances:
    - dbm: true
      host: <DB_HOST>
      port: <DB_PORT>
      username: datadog
      password: <DB_PASSWORD>
      dbname: <DB_NAME>
      ssl: prefer
      dbstrict: true
  ```
  

### PlanetScale metrics

`checks.d/planetscale.py` is PlanetScale's [custom check](https://github.com/planetscale/planetscale-datadog). Configure it with a Render secret file named `conf.d_planetscale.d_conf.yaml`, starting from [`conf.d/planetscale.d/conf.yaml.example`](conf.d/planetscale.d/conf.yaml.example). That example maps metric names the way [PlanetScale's docs](https://planetscale.com/docs/postgres/monitoring/prometheus-metrics-datadog-postgres) recommend.

`primary_hostnames` sends a branch primary's metrics with the Postgres DBM check's `reported_hostname`, so Database Monitoring associates them with that database instance.

Run the check's tests with:

```bash
python3 -m venv .venv
.venv/bin/pip install -r tests/requirements.txt
.venv/bin/pytest
```
