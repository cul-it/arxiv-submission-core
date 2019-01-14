"""Tests for annotation support in classic."""

from unittest import TestCase
import tempfile
from datetime import datetime
from pytz import UTC
import copy
from itertools import cycle
from flask import Flask

from ...rules.tests.data import titles
from ...domain.submission import Submission
from ...domain.agent import Agent, User
from ...domain.event import AddAnnotation, RemoveAnnotation, SetTitle
from ...domain.annotation import PossibleDuplicate
from ...services import classic
from ...rules import set_title
from ... import save, load, load_fast, domain, exceptions


class TestAddRemovePossibleDuplicateAnnotations(TestCase):
    """Test support for :class:`.PossibleDuplicate` annotations."""

    @classmethod
    def setUpClass(cls):
        """Instantiate an app for use with a SQLite database."""
        _, db = tempfile.mkstemp(suffix='.sqlite')
        cls.app = Flask('foo')
        cls.app.config['CLASSIC_DATABASE_URI'] = f'sqlite:///{db}'
        cls.app.config['ENABLE_ASYNC'] = 0

        with cls.app.app_context():
            classic.init_app(cls.app)

    def setUp(self):
        """Add some submissions with possibly matching titles."""
        with self.app.app_context():
            classic.create_all()
            STATUSES_TO_CHECK = [
                classic.models.Submission.SUBMITTED,
                classic.models.Submission.ON_HOLD,
                classic.models.Submission.NEXT_PUBLISH_DAY,
                classic.models.Submission.REMOVED,
                classic.models.Submission.USER_DELETED,
                classic.models.Submission.DELETED_ON_HOLD,
                classic.models.Submission.DELETED_PROCESSING,
                classic.models.Submission.DELETED_REMOVED,
                classic.models.Submission.DELETED_USER_EXPIRED
            ]
            with classic.transaction() as session:
                for status, (submission_id, title, user) \
                        in zip(cycle(STATUSES_TO_CHECK), titles.TITLES):
                    session.add(
                        classic.models.Submission(
                            submission_id=submission_id,
                            title=title,
                            submitter_id=user.native_id,
                            submitter_email=user.email,
                            status=status
                        )
                    )

    def tearDown(self):
        """Clear the database after each test."""
        with self.app.app_context():
            classic.drop_all()

    def test_add_annotation(self):
        user_id = 54321
        title = 'a lepton qed of colliders or interactions with strong field' \
                ' electron laser'
        creator = User(native_id=user_id, email='something@else.com')
        before = Submission(
            submission_id=2347441,
            creator=creator,
            owner=creator,
            created=datetime.now()
        )
        event_t = SetTitle(title=title, creator=creator)
        after = copy.deepcopy(before)
        before.metadata.title = title
        with self.app.app_context():
            events = list(set_title.check_for_similar_titles(
                event_t, before, after, creator)
            )

        self.assertEqual(len(events), 2, "Generates two events")
        for event in events:
            self.assertIsInstance(event, AddAnnotation,
                                  "Generates AddAnnotation events")
            self.assertIsInstance(event.annotation, PossibleDuplicate,
                                  "Annotations are PossibleDuplicates")

        for event in events:      # Apply the generated events.
            after = event.apply(after)

        # Checking a second time removes the previous annotations.
        with self.app.app_context():
            events = list(
                set_title.check_for_similar_titles(
                    event_t, before, after, creator
                )
            )
        self.assertEqual(len(events), 4, "Generates four events")
        for event in events[:2]:
            self.assertIsInstance(event, RemoveAnnotation,
                                  "Generates RemoveAnnotation events")

        for event in events[2:]:
            self.assertIsInstance(event, AddAnnotation,
                                  "Generates AddAnnotation events")
            self.assertIsInstance(event.annotation, PossibleDuplicate,
                                  "Annotations are PossibleDuplicates")

        # annotation = PossibleDuplicate(
        #    creator=creator,
        #    matching_id=ident,
        #    matching_title=title,
        #    matching_owner=submitter)
        # event = AddAnnotation(creator=creator, annotation=annotation)