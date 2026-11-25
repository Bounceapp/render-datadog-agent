from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests
import yaml
from datadog_checks.base import AgentCheck, ConfigurationError
from datadog_checks.base.checks.openmetrics.v2.scraper import OpenMetricsScraper

from planetscale import PlanetScaleCheck


def make_instance(**overrides):
    instance = {
        "planetscale_organization": "test-org",
        "ps_service_token_id": "id",
        "ps_service_token_secret": "secret",
        "namespace": "planetscale",
        "metrics": [".*"],
    }
    instance.update(overrides)
    return instance


def make_target(
    database_name="my-db",
    branch_name="main",
    metrics_path="/metrics/branch/abc",
    host="metrics.planetscale.com",
    extra_labels=None,
):
    labels = {
        "__metrics_path__": metrics_path,
        "__param_sig": "sig-value",
        "__param_exp": "12345",
        "__scheme__": "https",
        "planetscale_database_name": database_name,
        "planetscale_branch_name": branch_name,
        "planetscale_organization_name": "test-org",
    }
    if extra_labels:
        labels.update(extra_labels)
    return {"targets": [host], "labels": labels}


@pytest.fixture
def check():
    return PlanetScaleCheck("planetscale", {}, [make_instance()])


@pytest.fixture
def capture_scraper_configs(check):
    def run(instance, targets):
        captured = []

        def side_effect(config):
            captured.append(config)
            return MagicMock()

        with patch.object(check, "create_scraper", side_effect=side_effect):
            check.scrape_planetscale_targets(instance, targets)
        return captured

    return run


def _find_config_for_db(configs, db_name):
    return next(
        c for c in configs if f"planetscale_database_name:{db_name}" in c["tags"]
    )


class TestDatabaseTags:
    def test_applies_tags_for_matching_database(self, capture_scraper_configs):
        instance = make_instance(database_tags={"my-db": ["env:prod"]})
        configs = capture_scraper_configs(instance, [make_target(database_name="my-db")])
        assert "env:prod" in configs[0]["tags"]

    def test_skips_non_matching_database(self, capture_scraper_configs):
        instance = make_instance(database_tags={"other-db": ["env:prod"]})
        configs = capture_scraper_configs(instance, [make_target(database_name="my-db")])
        assert "env:prod" not in configs[0]["tags"]

    def test_additive_with_instance_level_tags(self, capture_scraper_configs):
        instance = make_instance(
            tags=["team:infra"],
            database_tags={"my-db": ["env:prod"]},
        )
        configs = capture_scraper_configs(instance, [make_target(database_name="my-db")])
        assert "team:infra" in configs[0]["tags"]
        assert "env:prod" in configs[0]["tags"]

    def test_supports_multiple_tags_per_database(self, capture_scraper_configs):
        instance = make_instance(
            database_tags={"my-db": ["env:prod", "team:billing", "tier:critical"]},
        )
        configs = capture_scraper_configs(instance, [make_target(database_name="my-db")])
        for tag in ("env:prod", "team:billing", "tier:critical"):
            assert tag in configs[0]["tags"]

    def test_applies_only_to_matching_target_in_mixed_set(self, capture_scraper_configs):
        instance = make_instance(database_tags={"prod-db": ["env:prod"]})
        targets = [
            make_target(database_name="prod-db"),
            make_target(database_name="staging-db"),
        ]
        configs = capture_scraper_configs(instance, targets)
        assert "env:prod" in _find_config_for_db(configs, "prod-db")["tags"]
        assert "env:prod" not in _find_config_for_db(configs, "staging-db")["tags"]

    def test_absent_config_is_noop(self, capture_scraper_configs):
        configs = capture_scraper_configs(make_instance(), [make_target()])
        assert not any(t.startswith("env:") for t in configs[0]["tags"])

    def test_null_config_is_noop(self, capture_scraper_configs):
        configs = capture_scraper_configs(
            make_instance(database_tags=None), [make_target()]
        )
        assert not any(t.startswith("env:") for t in configs[0]["tags"])

    def test_normalizes_single_tag_string(self, capture_scraper_configs):
        configs = capture_scraper_configs(
            make_instance(database_tags={"my-db": "env:prod"}),
            [make_target(database_name="my-db")],
        )
        assert "env:prod" in configs[0]["tags"]
        assert not any(len(tag) == 1 for tag in configs[0]["tags"])

    def test_invalid_tag_value_raises(self, capture_scraper_configs):
        with pytest.raises(ConfigurationError, match="database_tags\\[my-db\\]"):
            capture_scraper_configs(
                make_instance(database_tags={"my-db": None}),
                [make_target(database_name="my-db")],
            )

    def test_invalid_top_level_shape_raises(self, capture_scraper_configs):
        with pytest.raises(ConfigurationError, match="database_tags"):
            capture_scraper_configs(
                make_instance(database_tags=["env:prod"]),
                [make_target(database_name="my-db")],
            )


class TestTargetConfig:
    def test_discovered_labels_become_tags(self, capture_scraper_configs):
        configs = capture_scraper_configs(
            make_instance(), [make_target(database_name="my-db", branch_name="main")]
        )
        tags = configs[0]["tags"]
        assert "planetscale_database_name:my-db" in tags
        assert "planetscale_branch_name:main" in tags
        assert "planetscale_organization_name:test-org" in tags

    def test_meta_labels_are_not_promoted_to_tags(self, capture_scraper_configs):
        configs = capture_scraper_configs(make_instance(), [make_target()])
        tags = configs[0]["tags"]
        assert not any(t.startswith("__") for t in tags)

    def test_builds_url_from_host_path_and_params(self, capture_scraper_configs):
        configs = capture_scraper_configs(
            make_instance(),
            [make_target(metrics_path="/metrics/branch/xyz", host="api.example.com")],
        )
        url = configs[0]["openmetrics_endpoint"]
        assert url.startswith("https://api.example.com/metrics/branch/xyz")
        assert "sig=sig-value" in url
        assert "exp=12345" in url

    def test_adds_scheme_when_host_missing_scheme(self, capture_scraper_configs):
        configs = capture_scraper_configs(
            make_instance(), [make_target(host="api.example.com")]
        )
        assert configs[0]["openmetrics_endpoint"].startswith("https://")

    def test_skips_target_with_no_targets_field(self, capture_scraper_configs):
        configs = capture_scraper_configs(
            make_instance(), [{"labels": {"planetscale_database_name": "x"}}]
        )
        assert configs == []


class TestCheckValidation:
    def test_missing_organization_raises(self, check):
        instance = make_instance()
        del instance["planetscale_organization"]
        with pytest.raises(ConfigurationError, match="planetscale_organization"):
            check.check(instance)

    def test_missing_token_id_raises(self, check):
        instance = make_instance()
        del instance["ps_service_token_id"]
        with pytest.raises(ConfigurationError, match="ps_service_token_id"):
            check.check(instance)

    def test_missing_token_secret_raises(self, check):
        instance = make_instance()
        del instance["ps_service_token_secret"]
        with pytest.raises(ConfigurationError, match="ps_service_token_secret"):
            check.check(instance)


class TestApiConnectivity:
    def test_api_failure_emits_critical_service_check(self, check):
        with patch("planetscale.requests.get") as mock_get, patch.object(
            check, "service_check"
        ) as mock_sc:
            mock_get.side_effect = requests.exceptions.ConnectionError("nope")
            check.check(make_instance())
            names_and_statuses = [(c.args[0], c.args[1]) for c in mock_sc.call_args_list]
            assert ("planetscale.api.can_connect", AgentCheck.CRITICAL) in names_and_statuses

    def test_api_success_emits_ok_service_check(self, check):
        response = MagicMock()
        response.json.return_value = []
        response.raise_for_status.return_value = None
        with patch("planetscale.requests.get", return_value=response), patch.object(
            check, "service_check"
        ) as mock_sc:
            check.check(make_instance())
            names_and_statuses = [(c.args[0], c.args[1]) for c in mock_sc.call_args_list]
            assert ("planetscale.api.can_connect", AgentCheck.OK) in names_and_statuses


EXAMPLE_CONFIG = Path(__file__).parent.parent / "conf.d" / "planetscale.d" / "conf.yaml.example"

# Label sets as they arrive from bounce-data today: branch d2hp3rrvzv9h (main) and the
# dedicated read replica green-flamingo (652ojcnjp51o).
MAIN_PAYLOAD = """\
# TYPE planetscale_pods_cpu_util_percentages gauge
planetscale_pods_cpu_util_percentages{planetscale_pod="hzi-main-a",planetscale_component="hzinstance",planetscale_role="primary",planetscale_database_branch_id="d2hp3rrvzv9h"} 20
planetscale_pods_cpu_util_percentages{planetscale_pod="hzi-main-b",planetscale_component="hzinstance",planetscale_role="replica",planetscale_database_branch_id="d2hp3rrvzv9h"} 2
# TYPE planetscale_pods_mem_rss_bytes gauge
planetscale_pods_mem_rss_bytes{planetscale_pod="hzb-main",planetscale_component="hzbouncer",planetscale_database_branch_id="d2hp3rrvzv9h"} 100
planetscale_pods_mem_rss_bytes{planetscale_pod="hzbj-main",planetscale_component="hzbackupjob",planetscale_database_branch_id="d2hp3rrvzv9h"} 200
# TYPE planetscale_pgbouncer_current_connections gauge
planetscale_pgbouncer_current_connections{planetscale_pod="hzi-main-b",planetscale_component="hzinstance",planetscale_role="replica",planetscale_database_branch_id="d2hp3rrvzv9h"} 4
# TYPE planetscale_edge_postgres_active_connections gauge
planetscale_edge_postgres_active_connections{planetscale_database_branch_id="d2hp3rrvzv9h"} 30
# TYPE planetscale_pods_iops_total counter
planetscale_pods_iops_total{planetscale_pod="hzi-main-a",planetscale_component="hzinstance",planetscale_role="primary",planetscale_database_branch_id="d2hp3rrvzv9h"} 100
"""

REPLICA_PAYLOAD = """\
# TYPE planetscale_pods_cpu_util_percentages gauge
planetscale_pods_cpu_util_percentages{planetscale_pod="hzi-gf",planetscale_component="hzinstance",planetscale_role="replica",planetscale_database_branch_id="652ojcnjp51o"} 9
# TYPE planetscale_pods_mem_rss_bytes gauge
planetscale_pods_mem_rss_bytes{planetscale_pod="hzb-gf",planetscale_component="hzbouncer",planetscale_database_branch_id="652ojcnjp51o"} 300
"""

GREEN_FLAMINGO = {"planetscale_read_only_replica_name": "green-flamingo"}


@pytest.fixture
def example_instance():
    return yaml.safe_load(EXAMPLE_CONFIG.read_text())["instances"][0]


@pytest.fixture
def aggregator():
    from datadog_checks.base.stubs import aggregator as stub

    stub.reset()
    return stub


@pytest.fixture
def scrape(aggregator):
    def run(instance, payload, target_labels=None):
        check = PlanetScaleCheck("planetscale", {}, [instance])
        with patch.object(
            OpenMetricsScraper,
            "stream_connection_lines",
            return_value=iter(payload.splitlines()),
        ):
            check.scrape_planetscale_targets(
                instance, [make_target(database_name="bounce-data", extra_labels=target_labels)]
            )
        return aggregator

    return run


def instance_types(aggregator, metric_name):
    return sorted(
        tag.split(":", 1)[1]
        for metric in aggregator.metrics(metric_name)
        for tag in metric.tags
        if tag.startswith("planetscale_instance_type:")
    )


class TestExampleConfigNaming:
    def test_prefix_is_not_doubled(self, scrape, example_instance):
        aggregator = scrape(example_instance, MAIN_PAYLOAD)
        assert aggregator.metrics("planetscale_postgres.pods_cpu_util_percentages")
        assert not aggregator.metrics("planetscale.planetscale_pods_cpu_util_percentages")

    def test_docs_renames_apply(self, scrape, example_instance):
        aggregator = scrape(example_instance, MAIN_PAYLOAD)
        assert aggregator.metrics("planetscale_postgres.edge_active_connections")
        assert aggregator.metrics("planetscale_postgres.pgbouncer_connections")

    def test_counter_drops_total_suffix(self, scrape, example_instance):
        aggregator = scrape(example_instance, MAIN_PAYLOAD)
        assert aggregator.metrics("planetscale_postgres.pods_iops.count")

    def test_metrics_carry_no_host(self, example_instance):
        assert example_instance["empty_default_hostname"] is True


class TestInstanceType:
    def test_primary(self, scrape, example_instance):
        aggregator = scrape(example_instance, MAIN_PAYLOAD)
        assert "primary" in instance_types(aggregator, "planetscale_postgres.pods_cpu_util_percentages")

    def test_ha_replica(self, scrape, example_instance):
        aggregator = scrape(example_instance, MAIN_PAYLOAD)
        assert "ha_replica" in instance_types(aggregator, "planetscale_postgres.pods_cpu_util_percentages")

    def test_dedicated_replica(self, scrape, example_instance):
        aggregator = scrape(example_instance, REPLICA_PAYLOAD, GREEN_FLAMINGO)
        assert instance_types(aggregator, "planetscale_postgres.pods_cpu_util_percentages") == [
            "dedicated_replica"
        ]

    def test_pooler(self, scrape, example_instance):
        aggregator = scrape(example_instance, MAIN_PAYLOAD)
        assert "pooler" in instance_types(aggregator, "planetscale_postgres.pods_mem_rss_bytes")

    def test_dedicated_replica_pooler_is_pooler(self, scrape, example_instance):
        aggregator = scrape(example_instance, REPLICA_PAYLOAD, GREEN_FLAMINGO)
        assert instance_types(aggregator, "planetscale_postgres.pods_mem_rss_bytes") == ["pooler"]

    def test_backup(self, scrape, example_instance):
        aggregator = scrape(example_instance, MAIN_PAYLOAD)
        assert "backup" in instance_types(aggregator, "planetscale_postgres.pods_mem_rss_bytes")

    def test_edge(self, scrape, example_instance):
        aggregator = scrape(example_instance, MAIN_PAYLOAD)
        assert instance_types(aggregator, "planetscale_postgres.edge_active_connections") == ["edge"]

    def test_database_pod_pgbouncer_container_gets_pod_type(self, scrape, example_instance):
        aggregator = scrape(example_instance, MAIN_PAYLOAD)
        assert instance_types(aggregator, "planetscale_postgres.pgbouncer_connections") == ["ha_replica"]

    def test_every_series_gets_exactly_one_type(self, scrape, example_instance):
        aggregator = scrape(example_instance, MAIN_PAYLOAD)
        for name in aggregator.metric_names:
            if name.startswith("planetscale_postgres.telemetry"):
                continue
            for metric in aggregator.metrics(name):
                types = [t for t in metric.tags if t.startswith("planetscale_instance_type:")]
                assert len(types) == 1, (name, metric.tags)


class TestScraperOptionPassthrough:
    def test_collect_counters_with_distributions_reaches_scraper(self, capture_scraper_configs):
        configs = capture_scraper_configs(
            make_instance(collect_counters_with_distributions=True), [make_target()]
        )
        assert configs[0]["collect_counters_with_distributions"] is True
