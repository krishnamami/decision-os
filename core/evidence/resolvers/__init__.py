"""Fact resolvers — read document_index, build evidence, resolve to fact_nodes."""
from .income_resolver import IncomeFactResolver

__all__ = ["IncomeFactResolver"]
