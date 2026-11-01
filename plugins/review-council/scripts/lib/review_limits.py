READ_LINES = 240
CODEX_READ_LINES = 160
CODEX_SOURCE_READ_LINES = 200
REPOSITORY_EXPANSION_CALL_LIMIT = 16
SONNET_REPOSITORY_EXPANSION_CALL_LIMIT = 21
REPOSITORY_REFUTATION_CALL_RESERVE = 4
MANDATORY_REPOSITORY_READ_LIMIT = (
    REPOSITORY_EXPANSION_CALL_LIMIT - REPOSITORY_REFUTATION_CALL_RESERVE
)
LUNA_REPOSITORY_READ_BUDGET_MULTIPLIER = 6
CODEX_REVIEW_TURN_CALL_LIMIT = 2
LUNA_CODEX_REVIEW_TURN_CALL_LIMIT = 6
NO_TARGET_REPOSITORY_EXPANSION_CALL_LIMIT = (
    REPOSITORY_EXPANSION_CALL_LIMIT + REPOSITORY_REFUTATION_CALL_RESERVE
)
CLAUDE_MAX_TURNS = 160
PROVIDER_TURN_RESERVE = 2


def repository_read_budget_multiplier_for_model(model):
    name = model.rsplit('/', 1)[-1].lower() if isinstance(model, str) else ''
    return LUNA_REPOSITORY_READ_BUDGET_MULTIPLIER if (
        name == 'luna' or name.endswith('-luna')) else 1


def codex_review_turn_call_limit_for_model(model):
    return (LUNA_CODEX_REVIEW_TURN_CALL_LIMIT
            if repository_read_budget_multiplier_for_model(model) > 1
            else CODEX_REVIEW_TURN_CALL_LIMIT)


def repository_refutation_call_reserve_for_model(model=None):
    return REPOSITORY_REFUTATION_CALL_RESERVE * repository_read_budget_multiplier_for_model(model)


def repository_expansion_call_limit_for_seat(source_read_required, repository_source_target,
                                             model=None):
    multiplier = repository_read_budget_multiplier_for_model(model)
    limit = REPOSITORY_EXPANSION_CALL_LIMIT * multiplier
    if source_read_required and repository_source_target is None:
        name = model.rsplit('/', 1)[-1].lower() if isinstance(model, str) else ''
        if name == 'sonnet':
            limit = SONNET_REPOSITORY_EXPANSION_CALL_LIMIT
        return limit + REPOSITORY_REFUTATION_CALL_RESERVE * multiplier
    return limit


def mandatory_repository_read_limit_for_seat(source_read_required, repository_source_target,
                                             model=None):
    return (repository_expansion_call_limit_for_seat(
        source_read_required, repository_source_target, model)
        - repository_refutation_call_reserve_for_model(model))
