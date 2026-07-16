from __future__ import annotations

import json

import pytest

from gateway.devices import DeviceRegistry

YAML_DOC = """
trial: P3_run1
default_role: unwanted
devices:
  - mac: "A4:CF:12:3B:9E:01"
    label: hidden-target
    role: unwanted
  - mac: "3c:22:fb:aa:10:07"
    label: researcher-phone
    role: wanted
"""


def test_yaml_load_and_tagging(tmp_path):
    f = tmp_path / "devices.yaml"
    f.write_text(YAML_DOC)
    reg = DeviceRegistry.from_file(f)

    assert reg.trial == "P3_run1"
    # Case normalization: file had uppercase MAC, query with mixed case.
    assert reg.tag("A4:cf:12:3B:9e:01") == ("unwanted", "hidden-target")
    assert reg.tag("3c:22:fb:aa:10:07") == ("wanted", "researcher-phone")


def test_unlisted_mac_gets_default_role(tmp_path):
    f = tmp_path / "devices.yaml"
    f.write_text(YAML_DOC)
    reg = DeviceRegistry.from_file(f)
    role, label = reg.tag("ff:ff:ff:ff:ff:ff")
    assert role == "unwanted"
    assert label == "ff:ff:ff:ff:ff:ff"
    assert not reg.is_listed("ff:ff:ff:ff:ff:ff")


def test_json_variant(tmp_path):
    doc = {
        "default_role": "unwanted",
        "devices": [{"mac": "aa:bb:cc:dd:ee:ff", "label": "x", "role": "wanted"}],
    }
    f = tmp_path / "devices.json"
    f.write_text(json.dumps(doc))
    reg = DeviceRegistry.from_file(f)
    assert reg.tag("aa:bb:cc:dd:ee:ff") == ("wanted", "x")


def test_invalid_role_rejected(tmp_path):
    f = tmp_path / "devices.yaml"
    f.write_text("devices:\n  - mac: 'aa:bb:cc:dd:ee:ff'\n    role: sneaky\n")
    with pytest.raises(ValueError):
        DeviceRegistry.from_file(f)


def test_empty_registry_default():
    reg = DeviceRegistry.empty()
    assert reg.tag("aa:bb:cc:dd:ee:ff") == ("unwanted", "aa:bb:cc:dd:ee:ff")
