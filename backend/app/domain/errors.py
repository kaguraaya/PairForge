class DomainError(RuntimeError):
    """Base class for safe, user-facing domain failures."""


class CrossQuestionReferenceError(DomainError):
    pass


class MissingReferenceImageError(DomainError):
    pass


class StaleReferenceImageError(DomainError):
    pass


class InvalidStateTransitionError(DomainError):
    pass

