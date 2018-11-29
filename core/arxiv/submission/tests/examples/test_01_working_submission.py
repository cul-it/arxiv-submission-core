"""Example 1: working submission."""

from unittest import TestCase
import tempfile

from flask import Flask

from ...services import classic
from ... import save, load, domain, exceptions


class TestWorkingSubmission(TestCase):
    """
    Submitter creates a new submission, has completed some but not all fields.

    This is a typical scenario in which the user has missed a step, or left
    something required blank. These should get caught early if we designed
    the UI or API right, but it's possible that something slipped through.
    """

    @classmethod
    def setUpClass(cls):
        """Instantiate an app for use with a SQLite database."""
        _, db = tempfile.mkstemp(suffix='.sqlite')
        cls.app = Flask('foo')
        cls.app.config['CLASSIC_DATABASE_URI'] = f'sqlite:///{db}'

        with cls.app.app_context():
            classic.init_app(cls.app)

    def setUp(self):
        """Create and partially complete the submission."""
        self.submitter = domain.agent.User(1234, email='j.user@somewhere.edu',
                                           forename='Jane', surname='User',
                                           endorsements=['cs.DL', 'cs.IR'])
        self.defaults = {'creator': self.submitter}
        with self.app.app_context():
            classic.create_all()
            self.submission, self.events = save(
                domain.event.CreateSubmission(**self.defaults),
                domain.event.ConfirmAuthorship(**self.defaults),
                domain.event.ConfirmPolicy(**self.defaults),
                domain.event.SetTitle(title='the best title', **self.defaults)
            )

    def tearDown(self):
        """Clear the database after each test."""
        with self.app.app_context():
            classic.drop_all()

    def test_cannot_finalize_submission(self):
        """The submission cannot be finalized."""
        with self.app.app_context():
            with self.assertRaises(exceptions.InvalidEvent, msg=(
                    "Creating a FinalizeSubmission command results in an"
                    " exception.")):
                save(domain.event.FinalizeSubmission(**self.defaults),
                     submission_id=self.submission.submission_id)

        # Check the submission state.
        with self.app.app_context():
            submission, events = load(self.submission.submission_id)
            self.assertEqual(submission.status,
                             domain.submission.Submission.WORKING,
                             "The submission is in the working state")
            self.assertEqual(len(self.events), len(events),
                             "The same number of events were retrieved as"
                             " were initially saved.")

        # Check the database state.
        with self.app.app_context():
            session = classic.current_session()
            db_rows = session.query(classic.models.Submission).all()

            self.assertEqual(len(db_rows), 1,
                             "There is one row in the submission table")
            row = db_rows[0]
            self.assertEqual(row.type,
                             classic.models.Submission.NEW_SUBMISSION,
                             "The classic submission has type 'new'")
            self.assertEqual(row.status,
                             classic.models.Submission.NOT_SUBMITTED,
                             "The classic submission is in the NEW state")

    def test_cannot_replace_submission(self):
        """The submission cannot be replaced."""
        with self.app.app_context():
            with self.assertRaises(exceptions.InvalidEvent, msg=(
                    "Creating a CreateSubmissionVersion command results in an"
                    " exception.")):
                save(domain.event.CreateSubmissionVersion(**self.defaults),
                     submission_id=self.submission.submission_id)

        # Check the submission state.
        with self.app.app_context():
            submission, events = load(self.submission.submission_id)
            self.assertEqual(submission.status,
                             domain.submission.Submission.WORKING,
                             "The submission is in the working state")
            self.assertEqual(len(self.events), len(events),
                             "The same number of events were retrieved as"
                             " were initially saved.")

        # Check the database state.
        with self.app.app_context():
            session = classic.current_session()
            db_rows = session.query(classic.models.Submission).all()

            self.assertEqual(len(db_rows), 1,
                             "There is one row in the submission table")
            row = db_rows[0]
            self.assertEqual(row.type,
                             classic.models.Submission.NEW_SUBMISSION,
                             "The classic submission has type 'new'")
            self.assertEqual(row.status,
                             classic.models.Submission.NOT_SUBMITTED,
                             "The classic submission is in the not submitted"
                             " state")

    def test_cannot_withdraw_submission(self):
        """The submission cannot be withdrawn."""
        with self.app.app_context():
            with self.assertRaises(exceptions.InvalidEvent, msg=(
                    "Creating a RequestWithdrawal command results in an"
                    " exception.")):
                save(domain.event.RequestWithdrawal(reason="the best reason",
                                                    **self.defaults),
                     submission_id=self.submission.submission_id)

        # Check the submission state.
        with self.app.app_context():
            submission, events = load(self.submission.submission_id)
            self.assertEqual(submission.status,
                             domain.submission.Submission.WORKING,
                             "The submission is in the working state")
            self.assertEqual(len(self.events), len(events),
                             "The same number of events were retrieved as"
                             " were initially saved.")

        # Check the database state.
        with self.app.app_context():
            session = classic.current_session()
            db_rows = session.query(classic.models.Submission).all()

            self.assertEqual(len(db_rows), 1,
                             "There is one row in the submission table")
            row = db_rows[0]
            self.assertEqual(row.type,
                             classic.models.Submission.NEW_SUBMISSION,
                             "The classic submission has type 'new'")
            self.assertEqual(row.status,
                             classic.models.Submission.NOT_SUBMITTED,
                             "The classic submission is in the not submitted"
                             " state")

    def test_cannot_be_unfinalized(self):
        """The submission cannot be unfinalized."""
        with self.app.app_context():
            with self.assertRaises(exceptions.InvalidEvent, msg=(
                    "Creating an UnFinalizeSubmission command results in an"
                    " exception.")):
                save(domain.event.UnFinalizeSubmission(**self.defaults),
                     submission_id=self.submission.submission_id)

        # Check the submission state.
        with self.app.app_context():
            submission, events = load(self.submission.submission_id)
            self.assertEqual(submission.status,
                             domain.submission.Submission.WORKING,
                             "The submission is in the working state")
            self.assertEqual(len(self.events), len(events),
                             "The same number of events were retrieved as"
                             " were initially saved.")

        # Check the database state.
        with self.app.app_context():
            session = classic.current_session()
            db_rows = session.query(classic.models.Submission).all()

            self.assertEqual(len(db_rows), 1,
                             "There is one row in the submission table")
            row = db_rows[0]
            self.assertEqual(row.type,
                             classic.models.Submission.NEW_SUBMISSION,
                             "The classic submission has type 'new'")
            self.assertEqual(row.status,
                             classic.models.Submission.NOT_SUBMITTED,
                             "The classic submission is in the not submitted"
                             " state")
