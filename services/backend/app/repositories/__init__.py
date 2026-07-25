class PersistenceConflictError(ValueError):
    """The requested insert conflicts with an application invariant."""


class PersistenceScopeError(ValueError):
    """A referenced row does not belong to the requested user."""


__all__ = ["PersistenceConflictError", "PersistenceScopeError"]
