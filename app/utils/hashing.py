import hashlib
def data_hash(content: bytes) -> str: return hashlib.sha256(content).hexdigest()
