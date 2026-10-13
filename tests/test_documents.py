"""Stage 2 document discovery and storage tests."""

import pytest
from pathlib import Path
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.database.models import Tender, TenderDocument, DocumentVersion, DocumentEvent
from app.documents.classifier import classify_document, DocumentType
from app.documents.discovery import DocumentDiscovery, BlockedByVerification
from app.documents.downloader import DocumentDownloader, URLValidationError, is_safe_url
from app.documents.documents_service import DocumentsService
from app.schemas.documents import DocumentCandidate
from app.utils.dates import utcnow


class TestClassifier:
    """Test document classification."""

    def test_main_bid_classification(self):
        """Main Bid should be classified correctly."""
        assert classify_document("Main Bid", None) == DocumentType.MAIN_BID
        assert classify_document("Bid Document", None) == DocumentType.MAIN_BID
        assert classify_document("RFQ", None) == DocumentType.MAIN_BID

    def test_atc_classification(self):
        """ATC should be classified correctly."""
        assert classify_document("Buyer Added ATC", None) == DocumentType.ATC
        assert classify_document("Additional Terms and Conditions", None) == DocumentType.ATC
        assert classify_document("Addendum", None) == DocumentType.ATC

    def test_specification_classification(self):
        """Specification should be classified correctly."""
        assert classify_document("Specification", None) == DocumentType.SPECIFICATION
        assert classify_document("Technical Specifications", None) == DocumentType.SPECIFICATION
        assert classify_document("Requirements", None) == DocumentType.SPECIFICATION

    def test_boq_classification(self):
        """BOQ should be classified correctly."""
        assert classify_document("BOQ", None) == DocumentType.BOQ
        assert classify_document("Bill of Quantities", None) == DocumentType.BOQ
        assert classify_document(None, "boq.xlsx") == DocumentType.BOQ

    def test_corrigendum_classification(self):
        """Corrigendum should be classified correctly."""
        assert classify_document("Corrigendum", None) == DocumentType.CORRIGENDUM
        assert classify_document("Amendment", None) == DocumentType.CORRIGENDUM

    def test_unknown_classification(self):
        """Unknown documents should be classified as UNKNOWN."""
        assert classify_document("Some Random File", None) == DocumentType.UNKNOWN
        assert classify_document(None, "xyz.bin") == DocumentType.UNKNOWN


class TestURLValidation:
    """Test URL security validation."""

    def test_http_url_valid(self):
        """HTTP URLs should be accepted."""
        assert is_safe_url("http://example.com/file.pdf") is True

    def test_https_url_valid(self):
        """HTTPS URLs should be accepted."""
        assert is_safe_url("https://example.com/file.pdf") is True

    def test_file_url_rejected(self):
        """File:// URLs should be rejected."""
        assert is_safe_url("file:///etc/passwd") is False

    def test_javascript_url_rejected(self):
        """JavaScript URLs should be rejected."""
        assert is_safe_url("javascript:alert('xss')") is False

    def test_localhost_rejected(self):
        """Localhost URLs should be rejected."""
        assert is_safe_url("http://localhost/file.pdf") is False
        assert is_safe_url("http://127.0.0.1/file.pdf") is False

    def test_empty_url_rejected(self):
        """Empty URLs should be rejected."""
        assert is_safe_url("") is False
        assert is_safe_url(None) is False


@pytest.fixture
def discovery(settings: Settings):
    return DocumentDiscovery(settings)


@pytest.fixture
def sample_tender(db: Session) -> Tender:
    """Create a sample tender for testing."""
    tender = Tender(
        bid_number="GEM/2026/B/8014206",
        title="Sample Tender",
        status="ONGOING",
        source_fingerprint="test",
        first_seen_at=utcnow(),
        last_seen_at=utcnow(),
        source_internal_id="b_id_123",
        source_url="https://bidplus.gem.gov.in/showbidDocument/b_id_123",
    )
    db.add(tender)
    db.commit()
    return tender


class TestDiscovery:
    """Test document discovery service."""

    def test_build_tender_detail_url(self, discovery: DocumentDiscovery, sample_tender: Tender):
        """Should build correct tender detail URL."""
        url = discovery.build_tender_detail_url(sample_tender)
        assert "showbidDocument" in url
        assert "b_id_123" in url

    def test_blocked_detection_captcha(self, discovery: DocumentDiscovery):
        """Should detect CAPTCHA blocks."""
        html_with_captcha = "<html>verify you are human</html>"
        with pytest.raises(BlockedByVerification):
            discovery.discover_documents(None, html_with_captcha)

    def test_blocked_detection_403(self, discovery: DocumentDiscovery):
        """Should detect 403 blocks."""
        html_with_403 = "<html>403 forbidden</html>"
        with pytest.raises(BlockedByVerification):
            discovery.discover_documents(None, html_with_403)

    def test_empty_page_returns_no_documents(self, discovery: DocumentDiscovery):
        """Empty page should return no documents."""
        html_empty = "<html><body></body></html>"
        documents = discovery.discover_documents(None, html_empty)
        assert len(documents) == 0


@pytest.fixture
def sample_tender_storage(db: Session) -> Tender:
    """Create a sample tender for storage tests."""
    tender = Tender(
        bid_number="GEM/2026/B/8014207",
        title="Test Tender",
        status="ONGOING",
        source_fingerprint="test",
        first_seen_at=utcnow(),
        last_seen_at=utcnow(),
    )
    db.add(tender)
    db.commit()
    return tender


class TestDocumentStorage:
    """Test document storage and versioning."""

    def test_create_tender_document(self, db: Session, sample_tender_storage: Tender):
        """Should create a tender document record."""
        doc = TenderDocument(
            tender_id=sample_tender_storage.id,
            document_key="main_bid_1",
            document_type="MAIN_BID",
            source_url="https://example.com/bid.pdf",
            discovered_at=utcnow(),
            last_seen_at=utcnow(),
        )
        db.add(doc)
        db.commit()

        retrieved = db.query(TenderDocument).filter_by(id=doc.id).first()
        assert retrieved is not None
        assert retrieved.document_key == "main_bid_1"

    def test_create_document_version(self, db: Session, sample_tender_storage: Tender):
        """Should create document versions with content hash."""
        doc = TenderDocument(
            tender_id=sample_tender_storage.id,
            document_key="spec_1",
            document_type="SPECIFICATION",
            source_url="https://example.com/spec.pdf",
            discovered_at=utcnow(),
            last_seen_at=utcnow(),
        )
        db.add(doc)
        db.flush()

        version = DocumentVersion(
            document_id=doc.id,
            version_number=1,
            sha256="abc123def456" * 5,  # 60 chars
            file_size=1024,
            mime_type="application/pdf",
            extension="pdf",
            validation_status="VALID",
        )
        db.add(version)
        db.commit()

        retrieved = db.query(DocumentVersion).filter_by(id=version.id).first()
        assert retrieved is not None
        assert retrieved.version_number == 1
        assert retrieved.sha256 == "abc123def456" * 5

    def test_document_deduplication_by_hash(self, db: Session, sample_tender_storage: Tender):
        """Should detect when content is unchanged by hash."""
        doc = TenderDocument(
            tender_id=sample_tender_storage.id,
            document_key="doc_1",
            document_type="OTHER",
            source_url="https://example.com/doc.pdf",
            discovered_at=utcnow(),
            last_seen_at=utcnow(),
        )
        db.add(doc)
        db.flush()

        hash_value = "same_hash_123" * 5

        v1 = DocumentVersion(
            document_id=doc.id,
            version_number=1,
            sha256=hash_value,
            file_size=2048,
            validation_status="VALID",
        )
        db.add(v1)
        db.commit()

        # Check if same hash exists
        existing = db.query(DocumentVersion).filter(
            (DocumentVersion.document_id == doc.id)
            & (DocumentVersion.sha256 == hash_value)
        ).first()

        assert existing is not None
        assert existing.version_number == 1

    def test_document_version_increments(self, db: Session, sample_tender_storage: Tender):
        """Should increment version numbers when content changes."""
        doc = TenderDocument(
            tender_id=sample_tender_storage.id,
            document_key="atc_1",
            document_type="ATC",
            source_url="https://example.com/atc.pdf",
            discovered_at=utcnow(),
            last_seen_at=utcnow(),
        )
        db.add(doc)
        db.flush()

        # Version 1
        v1 = DocumentVersion(
            document_id=doc.id,
            version_number=1,
            sha256="hash_v1" * 9,
            validation_status="VALID",
        )
        db.add(v1)

        # Version 2 (different content)
        v2 = DocumentVersion(
            document_id=doc.id,
            version_number=2,
            sha256="hash_v2" * 9,
            validation_status="VALID",
        )
        db.add(v2)
        db.commit()

        versions = db.query(DocumentVersion).filter(
            DocumentVersion.document_id == doc.id
        ).order_by(DocumentVersion.version_number).all()

        assert len(versions) == 2
        assert versions[0].version_number == 1
        assert versions[1].version_number == 2


@pytest.fixture
def doc_with_versions(db: Session) -> TenderDocument:
    """Create a document with versions for testing."""
    tender = Tender(
        bid_number="GEM/2026/B/9999999",
        title="Event Test",
        status="ONGOING",
        source_fingerprint="test",
        first_seen_at=utcnow(),
        last_seen_at=utcnow(),
    )
    db.add(tender)
    db.flush()

    doc = TenderDocument(
        tender_id=tender.id,
        document_key="test_doc",
        document_type="OTHER",
        source_url="https://example.com/test.pdf",
        discovered_at=utcnow(),
        last_seen_at=utcnow(),
    )
    db.add(doc)
    db.flush()

    v1 = DocumentVersion(
        document_id=doc.id,
        version_number=1,
        sha256="hash1" * 13,
        validation_status="VALID",
    )
    db.add(v1)
    db.commit()

    return doc


class TestPDFDiscovery:
    """Tests for direct PDF discovery from tender detail URLs."""

    def test_direct_pdf_marker_creates_main_bid_candidate(self, sample_tender: Tender, discovery):
        """Direct PDF marker should create a MAIN_BID candidate."""
        # Create synthetic PDF marker
        pdf_marker = discovery._create_direct_pdf_marker(sample_tender.source_url, sample_tender)
        
        # Extract candidates
        candidates = discovery._extract_document_candidates(pdf_marker, sample_tender)
        
        # Verify
        assert len(candidates) == 1
        assert candidates[0].document_type == DocumentType.MAIN_BID
        assert candidates[0].display_name == "Main Bid"
        assert candidates[0].source_url == sample_tender.source_url

    def test_pdf_marker_detection_in_html(self, sample_tender: Tender, discovery):
        """Extraction should detect PDF marker in HTML."""
        pdf_marker = discovery._create_direct_pdf_marker(sample_tender.source_url, sample_tender)
        
        # Verify marker is present
        assert "Direct PDF detected at tender detail URL" in pdf_marker
        
        # Verify it's valid HTML
        assert "<html>" in pdf_marker
        assert "</html>" in pdf_marker

    def test_blocked_detection_in_pdf_marker_html(self, discovery):
        """Blocked indicators in PDF marker HTML should not trigger false blocking."""
        # PDF marker contains "Direct PDF" but should not be detected as blocked
        pdf_marker = "<html><body>Direct PDF detected</body></html>"
        
        # This should NOT raise BlockedByVerification
        result = discovery._is_blocked(pdf_marker)
        assert result is False  # Should not be detected as blocked

    def test_multiple_candidates_with_pdf(self, sample_tender: Tender, discovery):
        """PDF marker with additional HTML should extract only relevant candidates."""
        html = f'''
        <html>
        <body>
        Direct PDF detected at tender detail URL
        <a href="{sample_tender.source_url}" title="Main Bid">Main Bid PDF</a>
        <a href="https://example.com/atc.pdf" title="ATC">ATC</a>
        </body>
        </html>
        '''
        
        candidates = discovery._extract_document_candidates(html, sample_tender)
        
        # Should find both links
        assert len(candidates) == 2
        # First should be Main Bid (because it matches source_url)
        assert candidates[0].document_type == DocumentType.MAIN_BID


class TestDocumentEvents:
    """Test document event audit trail."""

    def test_record_discovered_event(self, db: Session, doc_with_versions: TenderDocument):
        """Should record DISCOVERED event."""
        event = DocumentEvent(
            document_id=doc_with_versions.id,
            event_type="DISCOVERED",
            detected_at=utcnow(),
        )
        db.add(event)
        db.commit()

        retrieved = db.query(DocumentEvent).filter_by(id=event.id).first()
        assert retrieved is not None
        assert retrieved.event_type == "DISCOVERED"

    def test_record_updated_event(self, db: Session):
        """Should record UPDATED event with old and new versions."""
        # Create tender and document
        tender = Tender(
            bid_number="GEM/2026/B/7777777",
            title="Update Test",
            status="ONGOING",
            source_fingerprint="test",
            first_seen_at=utcnow(),
            last_seen_at=utcnow(),
        )
        db.add(tender)
        db.flush()

        doc = TenderDocument(
            tender_id=tender.id,
            document_key="update_test",
            document_type="OTHER",
            source_url="https://example.com/test.pdf",
            discovered_at=utcnow(),
            last_seen_at=utcnow(),
        )
        db.add(doc)
        db.flush()

        # Create versions
        v1 = DocumentVersion(
            document_id=doc.id,
            version_number=1,
            sha256="oldversion" * 6 + "64",
            validation_status="VALID",
        )
        db.add(v1)
        db.flush()

        v2 = DocumentVersion(
            document_id=doc.id,
            version_number=2,
            sha256="newversion" * 6 + "64",
            validation_status="VALID",
        )
        db.add(v2)
        db.flush()

        # Create UPDATED event
        event = DocumentEvent(
            document_id=doc.id,
            event_type="UPDATED",
            old_version_id=v1.id,
            new_version_id=v2.id,
            detected_at=utcnow(),
            details="Content changed",
        )
        db.add(event)
        db.commit()

        retrieved = db.query(DocumentEvent).filter_by(id=event.id).first()
        assert retrieved.event_type == "UPDATED"
        assert retrieved.old_version_id == v1.id
        assert retrieved.new_version_id == v2.id
