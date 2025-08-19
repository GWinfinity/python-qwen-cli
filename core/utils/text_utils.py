from typing import Optional


def is_binary(
    data: Optional[bytes] = None,
    sample_size: int = 512,
) -> bool:
    """
    Checks if bytes data is likely binary by testing for the presence of a NULL byte.
    The presence of a NULL byte is a strong indicator that the data is not plain text.

    Args:
        data: The bytes to check.
        sample_size: The number of bytes from the start of the data to test.

    Returns:
        True if a NULL byte is found, False otherwise.
    """
    if data is None:
        return False

    # Take the first 'sample_size' bytes or the entire buffer if it's smaller
    sample_end = min(sample_size, len(data))
    sample = data[:sample_end]

    # Check for NULL byte (0x00) in the sample
    # This is more efficient than looping through each byte
    return b'\x00' in sample