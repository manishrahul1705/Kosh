"""Stage 4: Eligibility Engine Utilities.

Helper functions for fingerprinting, revisioning, and evaluation.
"""

import json
from datetime import datetime
from typing import Dict, List, Any, Optional
from hashlib import sha256

from app.eligibility.constants import AttributeKey, DocumentType, DocumentStatus


def calculate_seller_fingerprint(revision_data: Dict[str, Any]) -> str:
    """Calculate a deterministic fingerprint for a seller revision.

    Args:
        revision_data: Dictionary containing seller attributes and documents.

    Returns:
        SHA-256 fingerprint of the sorted canonical JSON.
    """
    # Extract attributes and documents
    attributes = revision_data.get("attributes", [])
    documents = revision_data.get("documents", [])

    # Sort attributes by key for deterministic output
    sorted_attributes = sorted(attributes, key=lambda x: x.get("key", ""))

    # Sort documents by type and filename for deterministic output
    sorted_documents = sorted(documents, key=lambda x: (x.get("document_type", ""), x.get("filename", "")))

    # Create canonical JSON
    canonical_data = {
        "attributes": sorted_attributes,
        "documents": sorted_documents,
        "timestamp": revision_data.get("created_at", datetime.utcnow().isoformat()),
    }

    # Convert to JSON string
    json_str = json.dumps(canonical_data, sort_keys=True, default=str)

    # Calculate SHA-256 fingerprint
    fingerprint = sha256(json_str.encode("utf-8")).hexdigest()

    return fingerprint


def get_seller_attribute_value(attributes: List[Dict[str, Any]], key: AttributeKey) -> Optional[Any]:
    """Get the value of a seller attribute by key.

    Args:
        attributes: List of seller attributes.
        key: Attribute key to look up.

    Returns:
        Attribute value or None if not found.
    """
    for attr in attributes:
        if attr.get("key") == key.value:
            if attr.get("value_type") == "TEXT":
                return attr.get("value_text")
            elif attr.get("value_type") == "NUMBER":
                return attr.get("value_number")
            elif attr.get("value_type") == "BOOLEAN":
                val = attr.get("value_text")
                if val is not None:
                    if isinstance(val, bool):
                        return val
                    return str(val).upper() == "TRUE"
                return attr.get("value_number") == 1
            elif attr.get("value_type") == "JSON":
                return json.loads(attr.get("value_json", "{}"))
    return None


def get_seller_document_by_type(documents: List[Dict[str, Any]], doc_type: DocumentType) -> Optional[Dict[str, Any]]:
    """Get the first document of a specific type.

    Args:
        documents: List of seller documents.
        doc_type: Document type to look up.

    Returns:
        Document or None if not found.
    """
    for doc in documents:
        if doc.get("document_type") == doc_type.value:
            return doc
    return None


def is_document_valid(document: Dict[str, Any], current_date: Optional[datetime] = None) -> bool:
    """Check if a document is valid (not expired).

    Args:
        document: Document dictionary.
        current_date: Optional datetime for testing.

    Returns:
        True if document is valid, False otherwise.
    """
    if not document:
        return False

    if document.get("status") != DocumentStatus.VERIFIED.value:
        return False

    expiry_date = document.get("expiry_date")
    if not expiry_date:
        return True

    current_date = current_date or datetime.utcnow()
    return expiry_date >= current_date


def is_requirement_mandatory(obligation_level: str) -> bool:
    """Check if a requirement is mandatory.

    Args:
        obligation_level: Obligation level (MANDATORY, OPTIONAL, etc.).

    Returns:
        True if mandatory, False otherwise.
    """
    return obligation_level.upper() == "MANDATORY"


