"""Tests for MemoryProvider ABC and MemoryProviderError."""
import sys
from pathlib import Path

import pytest

SERVER_DIR = str(Path(__file__).resolve().parent.parent)
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from services.memory_provider import MemoryProvider, MemoryProviderError


class TestMemoryProviderError:
    def test_memory_provider_error_carries_code_and_message(self):
        exc = MemoryProviderError(code="provider_unavailable", message="library not installed")

        assert exc.code == "provider_unavailable"
        assert str(exc) == "library not installed"
        assert exc.details == {}

    def test_memory_provider_error_defaults_message_to_code(self):
        exc = MemoryProviderError(code="memory_not_found")

        assert exc.code == "memory_not_found"
        assert str(exc) == "memory_not_found"

    def test_memory_provider_error_carries_details(self):
        exc = MemoryProviderError(
            code="transient",
            message="db timeout",
            details={"hint": "retry later"},
        )

        assert exc.code == "transient"
        assert exc.details == {"hint": "retry later"}

    def test_memory_provider_error_details_defaults_to_empty_dict(self):
        exc = MemoryProviderError(code="invalid_scope", message="bad input")

        assert exc.details == {}


class TestMemoryProviderIsAbstract:
    def test_memory_provider_is_abstract(self):
        with pytest.raises(TypeError):
            MemoryProvider()

    def test_partial_implementation_is_also_abstract(self):
        class PartialProvider(MemoryProvider):
            def save(self, content, scope, metadata):
                return {}

        with pytest.raises(TypeError):
            PartialProvider()

    def test_full_implementation_can_be_instantiated(self):
        class ConcreteProvider(MemoryProvider):
            def save(self, content, scope, metadata):
                return {}

            def retrieve(self, query, scope_filter, limit=10):
                return []

            def get(self, memory_id):
                return {}

            def delete(self, memory_id):
                return True

            def list_memories(self, scope_filter):
                return []

        provider = ConcreteProvider()
        assert isinstance(provider, MemoryProvider)
