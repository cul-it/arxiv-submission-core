"""Core persistence methods for submissions and submission events."""

from typing import Callable, List, Dict, Mapping, Tuple, Iterable, Optional
from functools import wraps
from collections import defaultdict

from flask import Flask

from arxiv.base import logging
from arxiv.base.globals import get_application_config, get_application_global

from .domain.submission import Submission, SubmissionMetadata, Author
from .domain.agent import Agent, User, System, Client
from .domain.event import *
from .services import classic
from .exceptions import InvalidEvent, InvalidStack, NoSuchSubmission, SaveError


logger = logging.getLogger(__name__)


def load(submission_id: int) -> Tuple[Submission, List[Event]]:
    """
    Load a submission and its history.

    This loads all events for the submission, and generates the most
    up-to-date representation based on those events.

    Parameters
    ----------
    submission_id : str
        Submission identifier.

    Returns
    -------
    :class:`.Submission`
        The current state of the submission.
    list
        Items are :class:`.Event`s, in order of their occurrence.

    Raises
    ------
    :class:`.NoSuchSubmission`
        Raised when a submission with the passed ID cannot be found.
    """
    try:
        return classic.get_submission(submission_id)
    except classic.NoSuchSubmission as e:
        raise NoSuchSubmission(f'No submission with id {submission_id}') from e


def load_submissions_for_user(user_id: int) -> List[Submission]:
    """
    Load active :class:`.Submission`s for a specific user.

    Parameters
    ----------
    user_id : int
        Unique identifier for the user.

    Returns
    -------
    list
        Items are :class:`.Submission` instances.

    """
    return classic.get_user_submissions_fast(user_id)


def load_fast(submission_id: int) -> Submission:
    """
    Load a :class:`.Submission` from its last projected state.

    This does not load and apply past events. The most recent stored submission
    state is loaded directly from the database.

    Parameters
    ----------
    submission_id : str
        Submission identifier.

    Returns
    -------
    :class:`.Submission`
        The current state of the submission.

    """
    try:
        return classic.get_submission_fast(submission_id)
    except classic.NoSuchSubmission as e:
        raise NoSuchSubmission(f'No submission with id {submission_id}') from e


def save(*events: Event, submission_id: Optional[str] = None) \
        -> Tuple[Submission, List[Event]]:
    """
    Commit a set of new :class:`.Event`s for a submission.

    This will persist the events to the database, along with the final
    state of the submission, and generate external notification(s) on the
    appropriate channels.

    Parameters
    ----------
    events : :class:`.Event`
        Events to apply and persist.
    submission_id : int
        The unique ID for the submission, if available. If not provided, it is
        expected that ``events`` includes a :class:`.CreateSubmission`.

    Returns
    -------
    :class:`arxiv.submission.domain.submission.Submission`
        The state of the submission after all events (including rule-derived
        events) have been applied. Updated with the submission ID, if a
        :class:`.CreateSubmission` was included.
    list
        A list of :class:`.Event` instances applied to the submission. Note
        that this list may contain more events than were passed, if event
        rules were triggered.

    Raises
    ------
    :class:`.NoSuchSubmission`
        Raised if ``submission_id`` is not provided and the first event is not
        a :class:`.CreateSubmission`, or ``submission_id`` is provided but
        no such submission exists.
    :class:`.InvalidEvent`
        If an invalid event is encountered, the entire operation is aborted
        and this exception is raised.
    :class:`.SaveError`
        There was a problem persisting the events and/or submission state
        to the database.

    """
    if len(events) == 0:
        raise ValueError('Must pass at least one event')
    events = list(events)   # Coerce to list so that we can index.
    prior: List[Event] = []
    before: Optional[Submission] = None

    # Get the current state of the submission from past events.
    if submission_id is not None:
        before, prior = classic.get_submission(submission_id)

    # Either we need a submission ID, or the first event must be a creation.
    elif events[0].submission_id is None \
            and not isinstance(events[0], CreateSubmission):
        raise NoSuchSubmission('Unable to determine submission')

    events = sorted(set(prior) | set(events), key=lambda e: e.created)
    applied: List[Event] = []

    for event in events:
        # Fill in event IDs, if they are missing.
        if event.submission_id is None and submission_id is not None:
            event.submission_id = submission_id

        # Mutation happens here; raises InvalidEvent.
        after = event.apply(before)
        applied.append(event)
        if not event.committed:
            # TODO: <-- emit event here.
            after, consequent_events = event.commit(classic.store_event)
            applied += consequent_events

        before = after
    return after, list(sorted(set(applied), key=lambda e: e.created))


def init_app(app: Flask) -> None:
    """Set default configuration parameters for an application instance."""
    classic.init_app(app)
    app.config.setdefault('ENABLE_CALLBACKS', 0)
    app.config.setdefault('ENABLE_ASYNC', 0)
