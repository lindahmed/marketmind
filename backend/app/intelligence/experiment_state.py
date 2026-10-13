"""Explicit experiment and dispatch state transitions."""

EXPERIMENT_TRANSITIONS = {
    "draft": {"approved", "rejected"},
    "approved": {"completed", "execution_failed"},
    "completed": set(),
    "execution_failed": set(),
    "rejected": set(),
}

DISPATCH_TRANSITIONS = {
    "dispatching": {"acknowledged", "failed", "completed", "execution_failed"},
    "acknowledged": {"completed", "execution_failed"},
    # A response can be lost after the workflow starts. A correctly authenticated
    # callback with the reserved execution ID is stronger evidence of execution.
    "failed": {"completed", "execution_failed"},
    "completed": set(),
    "execution_failed": set(),
}


def transition_experiment(experiment, target: str) -> None:
    if target not in EXPERIMENT_TRANSITIONS.get(experiment.status, set()):
        raise ValueError(f"Invalid experiment transition: {experiment.status} -> {target}")
    experiment.status = target


def transition_dispatch(dispatch, target: str) -> None:
    if target not in DISPATCH_TRANSITIONS.get(dispatch.status, set()):
        raise ValueError(f"Invalid dispatch transition: {dispatch.status} -> {target}")
    dispatch.status = target
