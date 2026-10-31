"""Unit tests for deterministic and runtime ID generation."""

from netcoop.utils.id_generator import (
    DeterministicIdGenerator,
    UuidGenerator,
    generate_id,
    set_id_generator,
)


def test_deterministic_id_generator():
    gen = DeterministicIdGenerator(start=1)
    assert gen.next_id("EVT") == "EVT-000001"
    assert gen.next_id("EVT") == "EVT-000002"
    assert gen.next_id("TASK") == "TASK-000001"
    assert gen.next_id("EVT") == "EVT-000003"

    gen.reset(start=10)
    assert gen.next_id("EVT") == "EVT-000010"


def test_uuid_generator():
    gen = UuidGenerator()
    id1 = gen.next_id("EVT")
    id2 = gen.next_id("EVT")
    assert id1.startswith("EVT-")
    assert id2.startswith("EVT-")
    assert id1 != id2


def test_global_id_generator_injection():
    gen = DeterministicIdGenerator(start=5)
    set_id_generator(gen)
    assert generate_id("F") == "F-000005"
    assert generate_id("F") == "F-000006"
