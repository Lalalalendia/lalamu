#!/usr/bin/env python3
"""Pinned Publisher11 scenario controls for Chaptera page-role evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from urllib.request import Request, urlopen

from page_role_sweep import derive_scenario_projection, run_probe, stable_hash

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data" / "page-role-sweep" / "scenario-controls.json"
SCHEMA = "lalamu.pub-page-role-scenario-controls.v1"
USER_AGENT = "lalamu-page-role-controls/1.0"
MAX_BYTES = 2 * 1024 * 1024

CONTROLS = [
    {
        "id": "publisher11-ec2asp",
        "source_repo": "azreasoners/ARG-webpage---Archived",
        "source_commit": "faf75b2996bb7f984365b9d4cb737af39c529ac6",
        "source_path": "ecasp/ec2asp.pub",
        "url": "https://raw.githubusercontent.com/azreasoners/ARG-webpage---Archived/faf75b2996bb7f984365b9d4cb737af39c529ac6/ecasp/ec2asp.pub",
        "expected_size": 114176,
        "expected_git_blob_sha1": "44b24ed03e84c7abb51a9d3bf71d27f958e8a96d",
        "expected_pgids": [[1, 0], [1, 1]],
        "expected_document_order_projected_seq_nums": [266, 358],
        "authority_note": (
            "Bounded same-document Publisher11 source/export evidence: current scenario "
            "Pgid membership filters DOCUMENT order to PAGE266, PAGE358."
        ),
    },
    {
        "id": "publisher11-help",
        "source_repo": "Planet-Source-Code/hartoto-flexible-phoone-book__1-69597",
        "source_commit": "1400f033db5f4a57cca6d5392f551943271b7f72",
        "source_path": "help.pub",
        "url": "https://raw.githubusercontent.com/Planet-Source-Code/hartoto-flexible-phoone-book__1-69597/1400f033db5f4a57cca6d5392f551943271b7f72/help.pub",
        "expected_size": 396800,
        "expected_git_blob_sha1": "099df5d6ee9acb301669d1e25c47bd2cbe26a953",
        "expected_pgids": [[1, 0]],
        "expected_document_order_projected_seq_nums": [266],
        "authority_note": (
            "Independent Publisher11 source/export control reproducing the bounded "
            "current-scenario Pgid membership law."
        ),
    },
]


def fetch_bytes(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with urlopen(request, timeout=45) as response:
        declared = response.headers.get("Content-Length")
        if declared and int(declared) > MAX_BYTES:
            raise RuntimeError(f"declared Content-Length exceeds bound: {declared}")
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise RuntimeError(f"download exceeds bound: {len(data)}")
    return data


def git_blob_sha1(data: bytes) -> str:
    return hashlib.sha1(f"blob {len(data)}\0".encode("ascii") + data).hexdigest()


def verify_source(control: dict, data: bytes) -> dict:
    actual_blob = git_blob_sha1(data)
    if len(data) != control["expected_size"]:
        raise RuntimeError(
            f"{control['id']}: size {len(data)} != {control['expected_size']}"
        )
    if actual_blob != control["expected_git_blob_sha1"]:
        raise RuntimeError(
            f"{control['id']}: git blob {actual_blob} != "
            f"{control['expected_git_blob_sha1']}"
        )
    return {
        "byte_len": len(data),
        "git_blob_sha1": actual_blob,
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def run_control(probe: Path, control: dict, root: Path, timeout: float) -> dict:
    data = fetch_bytes(control["url"])
    source_identity = verify_source(control, data)
    fixture = root / f"{control['id']}.pub"
    fixture.write_bytes(data)

    observation = run_probe(probe, fixture, timeout)
    if observation.get("status") != "success":
        raise RuntimeError(
            f"{control['id']}: probe failed: {json.dumps(observation, sort_keys=True)}"
        )

    raw_receipt = observation["receipt"]
    projection = derive_scenario_projection(raw_receipt)
    if projection.get("status") != "resolved":
        raise RuntimeError(
            f"{control['id']}: scenario projection unavailable: "
            f"{projection.get('reason')}"
        )
    if projection.get("pgids") != control["expected_pgids"]:
        raise RuntimeError(
            f"{control['id']}: Pgid mismatch: {projection.get('pgids')} != "
            f"{control['expected_pgids']}"
        )
    if (
        projection.get("document_order_projected_seq_nums")
        != control["expected_document_order_projected_seq_nums"]
    ):
        raise RuntimeError(
            f"{control['id']}: projected PAGE order mismatch: "
            f"{projection.get('document_order_projected_seq_nums')} != "
            f"{control['expected_document_order_projected_seq_nums']}"
        )

    return {
        "id": control["id"],
        "source_repo": control["source_repo"],
        "source_commit": control["source_commit"],
        "source_path": control["source_path"],
        "source_identity": source_identity,
        "authority_note": control["authority_note"],
        "expected_pgids": control["expected_pgids"],
        "expected_document_order_projected_seq_nums": control[
            "expected_document_order_projected_seq_nums"
        ],
        "projection": projection,
        "raw_observation_receipt_sha256": stable_hash(raw_receipt),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe-bin", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args()

    probe = args.probe_bin.resolve()
    with tempfile.TemporaryDirectory(prefix="lalamu-page-role-controls-") as tmp:
        root = Path(tmp)
        controls = [
            run_control(probe, control, root, args.timeout) for control in CONTROLS
        ]

    receipt = {
        "schema": SCHEMA,
        "chaptera_upstream_commit": os.environ.get("CHAPTERA_UPSTREAM_COMMIT"),
        "control_count": len(controls),
        "resolved_exact_count": len(controls),
        "interpretation": (
            "These are bounded Publisher11 scenario controls. They prove Pgid->Page.Oid "
            "membership plus DOCUMENT-order projection for these source/export specimens; "
            "they do not make scenario membership a universal visible-page rule."
        ),
        "controls": controls,
    }
    receipt["receipt_sha256"] = stable_hash(receipt)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "schema": receipt["schema"],
                "chaptera_upstream_commit": receipt["chaptera_upstream_commit"],
                "control_count": receipt["control_count"],
                "resolved_exact_count": receipt["resolved_exact_count"],
                "receipt_sha256": receipt["receipt_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
