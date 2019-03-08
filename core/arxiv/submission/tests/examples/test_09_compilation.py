"""Compilation workflow during submission."""

from unittest import TestCase, mock
import tempfile

from flask import Flask

from ...services import classic, plaintext, classifier, compiler
from ... import save, load, load_fast, domain, exceptions, tasks, core, rules
from ...rules.tests.data.titles import TITLES


CCO = 'http://creativecommons.org/publicdomain/zero/1.0/'
TEX = domain.submission.SubmissionContent.Format('tex')


class TestSourceSizeLimits(TestCase):
    """Submitter has added their source; size limits should be checked."""

    @classmethod
    def setUpClass(cls):
        """Instantiate an app for use with a SQLite database."""
        _, db = tempfile.mkstemp(suffix='.sqlite')
        cls.app = Flask('foo')
        cls.app.config['CLASSIC_DATABASE_URI'] = f'sqlite:///{db}'
        cls.app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

        # with cls.app.app_context():
        classic.init_app(cls.app)

    def setUp(self):
        """Set up the database."""
        self.submitter = domain.agent.User(1234, email='j.user@somewhere.edu',
                                           forename='Jane', surname='User',
                                           endorsements=['cs.AI', 'cs.IR'])
        self.defaults = {'creator': self.submitter}
        with self.app.app_context():
            classic.create_all()

            title = 'cool title, bro'
            self.doi = "10.01234/56789"
            self.upload_id = '123'
            self.checksum = "a9s9k342900ks03330029"
            self.output_format = compiler.Format.PDF
            self.submission, self.events = save(
                domain.event.CreateSubmission(**self.defaults),
                domain.event.ConfirmContactInformation(**self.defaults),
                domain.event.ConfirmAuthorship(**self.defaults),
                domain.event.ConfirmPolicy(**self.defaults),
                domain.event.SetTitle(title=title, **self.defaults),
                domain.event.SetLicense(license_uri=CCO,
                                        license_name="CC0 1.0",
                                        **self.defaults),
                domain.event.SetPrimaryClassification(category="cs.AI",
                                                      **self.defaults),
                domain.event.SetAbstract(abstract="Very abstract " * 20,
                                         **self.defaults),
                domain.event.SetComments(comments="Fine indeed " * 10,
                                         **self.defaults),
                domain.event.SetJournalReference(journal_ref="Foo 1992",
                                                 **self.defaults),
                domain.event.SetDOI(doi=self.doi, **self.defaults),
                domain.event.SetAuthors(authors_display='Robert Paulson (FC)',
                                        **self.defaults),
            )

    @mock.patch(f'{tasks.__name__}.get_application_config',
                mock.MagicMock(return_value={'ENABLE_ASYNC': 0}))
    @mock.patch(f'{domain.__name__}.event.event.get_application_config',
                mock.MagicMock(return_value={'ENABLE_CALLBACKS': 1}))
    def test_add_source(self):
        """User adds source content to submission."""
        # Add some reasonable source content.
        with self.app.app_context():
            submission, events = save(
                domain.event.SetUploadPackage(checksum=self.checksum,
                                              source_format=TEX,
                                              identifier=self.upload_id,
                                              uncompressed_size=2_593_992,
                                              compressed_size=30_992,
                                              **self.defaults),
                submission_id=self.submission.submission_id
            )

        # All should be well.
        with self.app.app_context():
            submission, events = load(self.submission.submission_id)
            self.assertFalse(submission.is_on_hold,
                             "No hold; source size is OK")

            session = classic.current_session()
            db_row = session.query(classic.models.Submission) \
                .order_by(classic.models.Submission.submission_id.asc()) \
                .first()
            self.assertFalse(db_row.is_on_hold(), "Database reflects hold")

        # Now add a bunch of stuff that is huge uncompressed.
        with self.app.app_context():
            submission, events = save(
                domain.event.SetUploadPackage(checksum=self.checksum,
                                              source_format=TEX,
                                              identifier=self.upload_id,
                                              uncompressed_size=2_392_593_992,
                                              compressed_size=30_992,
                                              **self.defaults),
                submission_id=self.submission.submission_id
            )

        # The submission should be on hold.
        with self.app.app_context():
            submission, events = load(self.submission.submission_id)
            self.assertTrue(submission.is_on_hold,
                            "Hold! Uncompressed source is huge")

            session = classic.current_session()
            db_row = session.query(classic.models.Submission) \
                .order_by(classic.models.Submission.submission_id.asc()) \
                .first()
            self.assertTrue(db_row.is_on_hold(), "Database reflects hold")

        # Update the source; uncompressed size back to reasonable levels.
        with self.app.app_context():
            submission, events = save(
                domain.event.UpdateUploadPackage(checksum=self.checksum,
                                                 source_format=TEX,
                                                 uncompressed_size=2_593_992,
                                                 compressed_size=30_992,
                                                 **self.defaults),
                submission_id=self.submission.submission_id
            )

        # Hold is cleared.
        with self.app.app_context():
            submission, events = load(self.submission.submission_id)
            self.assertFalse(submission.is_on_hold,
                             "Hold is cleared; uncompressed size is OK")

            session = classic.current_session()
            db_row = session.query(classic.models.Submission) \
                .order_by(classic.models.Submission.submission_id.asc()) \
                .first()
            self.assertFalse(db_row.is_on_hold(), "Database reflects hold")

        # Something wonky happens, and the compressed size skyrockets.
        with self.app.app_context():
            submission, events = save(
                domain.event.UpdateUploadPackage(checksum=self.checksum,
                                                 source_format=TEX,
                                                 uncompressed_size=2_593_992,
                                                 compressed_size=3_000_123_992,
                                                 **self.defaults),
                submission_id=self.submission.submission_id
            )

        # The submission should be on hold.
        with self.app.app_context():
            submission, events = load(self.submission.submission_id)
            self.assertTrue(submission.is_on_hold,
                            "Hold! Ccompressed source is huge")

            session = classic.current_session()
            db_row = session.query(classic.models.Submission) \
                .order_by(classic.models.Submission.submission_id.asc()) \
                .first()
            self.assertTrue(db_row.is_on_hold(), "Database reflects hold")


class TestSubmissionCompilation(TestCase):
    """Submitter has added their source, and is compiling to preview."""

    @classmethod
    def setUpClass(cls):
        """Instantiate an app for use with a SQLite database."""
        _, db = tempfile.mkstemp(suffix='.sqlite')
        cls.app = Flask('foo')
        cls.app.config['CLASSIC_DATABASE_URI'] = f'sqlite:///{db}'
        cls.app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        cls.app.config['JWT_SECRET'] = 'foosecret'

        # with cls.app.app_context():
        classic.init_app(cls.app)

    def setUp(self):
        """Set up the database."""
        self.submitter = domain.agent.User(1234, email='j.user@somewhere.edu',
                                           forename='Jane', surname='User',
                                           endorsements=['cs.AI', 'cs.IR'])
        self.defaults = {'creator': self.submitter}
        with self.app.app_context():
            classic.create_all()

            title = 'cool title, bro'
            self.doi = "10.01234/56789"
            self.upload_id = '123'
            self.checksum = "a9s9k342900ks03330029"
            self.output_format = compiler.Format.PDF
            self.submission, self.events = save(
                domain.event.CreateSubmission(**self.defaults),
                domain.event.ConfirmContactInformation(**self.defaults),
                domain.event.ConfirmAuthorship(**self.defaults),
                domain.event.ConfirmPolicy(**self.defaults),
                domain.event.SetTitle(title=title, **self.defaults),
                domain.event.SetLicense(license_uri=CCO,
                                        license_name="CC0 1.0",
                                        **self.defaults),
                domain.event.SetPrimaryClassification(category="cs.AI",
                                                      **self.defaults),
                domain.event.SetAbstract(abstract="Very abstract " * 20,
                                         **self.defaults),
                domain.event.SetComments(comments="Fine indeed " * 10,
                                         **self.defaults),
                domain.event.SetJournalReference(journal_ref="Foo 1992",
                                                 **self.defaults),
                domain.event.SetDOI(doi=self.doi, **self.defaults),
                domain.event.SetAuthors(authors_display='Robert Paulson (FC)',
                                        **self.defaults),
                domain.event.SetUploadPackage(checksum=self.checksum,
                                              source_format=TEX,
                                              identifier=self.upload_id,
                                              uncompressed_size=593992,
                                              compressed_size=593992,
                                              **self.defaults)
            )

    @mock.patch(f'{tasks.__name__}.get_application_config',
                mock.MagicMock(return_value={'ENABLE_ASYNC': 0}))
    @mock.patch(f'{domain.__name__}.event.event.get_application_config',
                mock.MagicMock(return_value={'ENABLE_CALLBACKS': 1}))
    @mock.patch(f'{plaintext.__name__}.request_extraction',
                lambda *a, **k: None)
    @mock.patch(f'{plaintext.__name__}.extraction_is_complete',
                lambda *a, **k: True)
    @mock.patch(f'{plaintext.__name__}.retrieve_content',
                lambda *a, **k: b'foo content')
    @mock.patch(f'{compiler.__name__}.compilation_is_complete')
    @mock.patch(f'{compiler.__name__}.get_status')
    def test_compilation(self, mock_get_status, mock_compile_complete):
        """The submission source content is compiled to PDF."""
        mock_compile_complete.side_effect = [compiler.NoSuchResource('nope'),
                                             False, True]
        mock_get_status.return_value = compiler.CompilationStatus(
            upload_id=self.upload_id,
            status=compiler.Status.SUCCEEDED,
            checksum=self.checksum,
            output_format=self.output_format,
            size_bytes=5_030_930,
        )
        with self.app.app_context():
            task_id = compiler.get_task_id(self.upload_id, self.checksum,
                                           self.output_format)
            submission, events = save(
                domain.event.AddProcessStatus(
                    creator=self.submitter,
                    process=domain.event.AddProcessStatus.Process.COMPILATION,
                    status=domain.event.AddProcessStatus.Status.REQUESTED,
                    identifier=task_id,
                    service=compiler.NAME,
                    version=compiler.VERSION,
                ),
                submission_id=self.submission.submission_id
            )
            self.assertEqual(mock_compile_complete.call_count, 3,
                             "Completion status is checked three times")

        # Check the classic database.
        with self.app.app_context():
            submission, events = load(self.submission.submission_id)
            self.assertFalse(submission.is_on_hold, "No hold; PDF size is OK")
            self.assertEqual(submission.latest_compilation.source_id,
                             self.upload_id,
                             "The compilation process is recorded")
            self.assertEqual(submission.latest_compilation.checksum,
                             self.checksum,
                             "The compilation process is recorded")
            self.assertEqual(submission.latest_compilation.output_format,
                             self.output_format.value,
                             "The compilation process is recorded")
            self.assertEqual(submission.latest_compilation.status,
                             domain.Compilation.Status.SUCCEEDED,
                             "Compilation success is noted")

        # Check the classic database.
        with self.app.app_context():
            session = classic.current_session()
            db_row = session.query(classic.models.Submission) \
                .order_by(classic.models.Submission.submission_id.asc()) \
                .first()
            self.assertEqual(db_row.must_process, 0,
                             "must_process flag is off because compilation was"
                             " successful and source hasn't changed")

    @mock.patch(f'{tasks.__name__}.get_application_config',
                mock.MagicMock(return_value={'ENABLE_ASYNC': 0}))
    @mock.patch(f'{domain.__name__}.event.event.get_application_config',
                mock.MagicMock(return_value={'ENABLE_CALLBACKS': 1}))
    @mock.patch(f'{plaintext.__name__}.request_extraction',
                lambda *a, **k: None)
    @mock.patch(f'{plaintext.__name__}.extraction_is_complete',
                lambda *a, **k: True)
    @mock.patch(f'{plaintext.__name__}.retrieve_content',
                lambda *a, **k: b'foo content')
    @mock.patch(f'{compiler.__name__}.compilation_is_complete')
    @mock.patch(f'{compiler.__name__}.get_status')
    def test_pdf_oversize(self, mock_get_status, mock_compile_complete):
        """The generated PDF is too large."""
        mock_compile_complete.side_effect = [compiler.NoSuchResource('nope'),
                                             True]
        mock_get_status.return_value = compiler.CompilationStatus(
            upload_id=self.upload_id,
            status=compiler.Status.SUCCEEDED,
            checksum=self.checksum,
            output_format=self.output_format,
            size_bytes=5_000_030_930,   # That's a big PDF.
        )
        with self.app.app_context():
            task_id = compiler.get_task_id(self.upload_id, self.checksum,
                                           self.output_format)
            submission, events = save(
                domain.event.AddProcessStatus(
                    creator=self.submitter,
                    process=domain.event.AddProcessStatus.Process.COMPILATION,
                    status=domain.event.AddProcessStatus.Status.REQUESTED,
                    identifier=task_id,
                    service=compiler.NAME,
                    version=compiler.VERSION,
                ),
                submission_id=self.submission.submission_id
            )
            self.assertEqual(mock_compile_complete.call_count, 2,
                             "Completion status is checked three times")

        # Check the classic database.
        with self.app.app_context():
            submission, events = load(self.submission.submission_id)
            self.assertTrue(submission.is_on_hold, "On hold; PDF is huge")
            self.assertEqual(submission.latest_compilation.source_id,
                             self.upload_id,
                             "The compilation process is recorded")
            self.assertEqual(submission.latest_compilation.checksum,
                             self.checksum,
                             "The compilation process is recorded")
            self.assertEqual(submission.latest_compilation.output_format,
                             self.output_format.value,
                             "The compilation process is recorded")
            self.assertEqual(submission.latest_compilation.status,
                             domain.Compilation.Status.SUCCEEDED,
                             "Compilation success is noted")

        # Check the classic database.
        with self.app.app_context():
            session = classic.current_session()
            db_row = session.query(classic.models.Submission) \
                .order_by(classic.models.Submission.submission_id.asc()) \
                .first()
            self.assertEqual(db_row.must_process, 0,
                             "must_process flag is off because compilation was"
                             " successful and source hasn't changed")
            self.assertTrue(db_row.is_on_hold(), "Database reflects hold status")


    def tearDown(self):
        """Clear the database after each test."""
        with self.app.app_context():
            classic.drop_all()