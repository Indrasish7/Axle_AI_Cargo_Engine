import hashlib
import time
import datetime
from sqlalchemy.orm import Session
from src.database import IdempotencyKey

def generate_idempotency_hash(sender_id: str, raw_text: str, window_seconds: int = 300) -> str:
    """
    Generates a cryptographic SHA-256 hash using the sender_id, normalized raw text, 
    and a deterministic timestamp window (e.g. 5-minute bucket) to guard against
    duplicate webhook hits.
    
    Hash layout: sha256(sender_id + normalized_raw_text + timestamp_window)
    """
    # Create a time window bucket (e.g., if epoch = 1716301234 and window_seconds = 300,
    # then timestamp_window = 5721004. This bucket changes every 5 minutes.)
    timestamp_window = int(time.time() // window_seconds)
    
    # Normalize text to avoid whitespace and case discrepancies
    normalized_text = "".join(raw_text.split()).lower()
    
    # Combine ingredients into standard pre-image
    preimage = f"{sender_id}:{normalized_text}:{timestamp_window}"
    
    # Generate SHA-256
    return hashlib.sha256(preimage.encode("utf-8")).hexdigest()

def is_duplicate_request(session: Session, hash_key: str) -> bool:
    """
    Queries the database idempotency table within the transaction to see
    if the hash key already exists.
    """
    exists = session.query(IdempotencyKey).filter(IdempotencyKey.hash_key == hash_key).first()
    return exists is not None

def register_request_hash(session: Session, hash_key: str) -> None:
    """
    Inserts a new idempotency key record into the database to block
    any future duplicate webhook hits within the timestamp window.
    """
    new_record = IdempotencyKey(
        hash_key=hash_key,
        created_at=datetime.datetime.utcnow()
    )
    session.add(new_record)
