"""Accounting rules: reported totals that must equal a signed sum of components.

Rules live in `config/accounting_rules.json`. Each says
`total == sum(coefficient * component)` for facts of one company, scope,
period end, period type, and unit. Amounts are compared with the sign the
statement presents them with (outflows and expenses negative), so
coefficients are usually +1.

A component may be declared optional with a written assumption, such as a
reconciling line the filing shows as nil. When an optional component is
absent the rule still runs, and the validation report records the
assumption every time it is applied. Nothing else is ever treated as zero.
"""

from collections import Counter
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from finura.schemas.io import load_model
from finura.schemas.types import ConceptId, FiniteNumber, NonEmptyStr
from finura.sectors import StatementModel

RuleId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")]


class RuleComponent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    concept: ConceptId
    # Integers only, so sums of integer amounts stay exact.
    coefficient: StrictInt
    optional: bool = False
    # Required for optional components: what an absent value is taken to mean.
    assumption_when_absent: NonEmptyStr | None = None

    @model_validator(mode="after")
    def _is_well_formed(self) -> Self:
        if self.coefficient == 0:
            raise ValueError(f"{self.concept}: coefficient must be non-zero")
        if self.optional != (self.assumption_when_absent is not None):
            raise ValueError(f"{self.concept}: assumption_when_absent is required exactly for optional components")
        return self


class AccountingRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: RuleId
    description: NonEmptyStr
    statement_models: tuple[StatementModel, ...] = Field(min_length=1)
    total: ConceptId
    components: tuple[RuleComponent, ...] = Field(min_length=1)
    # Absolute tolerance in the facts' unit; 0 means exact equality.
    tolerance: FiniteNumber = 0
    # Required when tolerance > 0: the filing convention or observed rounding that justifies it.
    tolerance_basis: NonEmptyStr | None = None

    @model_validator(mode="after")
    def _is_well_formed(self) -> Self:
        if len(set(self.statement_models)) != len(self.statement_models):
            raise ValueError(f"{self.rule_id}: duplicate statement models")
        concepts = [self.total, *(component.concept for component in self.components)]
        if len(set(concepts)) != len(concepts):
            raise ValueError(f"{self.rule_id}: a concept appears more than once")
        if all(component.optional for component in self.components):
            raise ValueError(f"{self.rule_id}: at least one component must be required")
        if self.tolerance < 0:
            raise ValueError(f"{self.rule_id}: tolerance cannot be negative")
        if (self.tolerance > 0) != (self.tolerance_basis is not None):
            raise ValueError(f"{self.rule_id}: tolerance_basis is required exactly when tolerance is above zero")
        return self

    @property
    def concepts(self) -> tuple[str, ...]:
        return (self.total, *(component.concept for component in self.components))

    @property
    def required_concepts(self) -> tuple[str, ...]:
        return (self.total, *(c.concept for c in self.components if not c.optional))


class AccountingRuleSet(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    record_type: Literal["accounting_rules"] = "accounting_rules"
    rules: tuple[AccountingRule, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _rule_ids_are_unique(self) -> Self:
        counts = Counter(rule.rule_id for rule in self.rules)
        duplicates = sorted(rule_id for rule_id, count in counts.items() if count > 1)
        if duplicates:
            raise ValueError(f"duplicate rule_id values: {duplicates}")
        return self


def load_accounting_rules(path: Path) -> AccountingRuleSet:
    return load_model(path, AccountingRuleSet)
