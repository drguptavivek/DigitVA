"""Service package.

Keep this package init intentionally light. Eagerly importing the full service tree
creates circular import chains when lower-level utilities need a single service module.
Callers should import concrete service modules directly.
"""

__all__: list[str] = []
