def format_memory_usage(bytes_: int) -> str:
    """
    格式化内存使用量为易读的字符串表示
    
    Args:
        bytes_: 内存使用量，以字节为单位
        
    Returns:
        格式化后的内存使用量字符串，单位为 KB、MB 或 GB
    """
    gb = bytes_ / (1024 * 1024 * 1024)
    if bytes_ < 1024 * 1024:
        return f"{(bytes_ / 1024):.1f} KB"
    if bytes_ < 1024 * 1024 * 1024:
        return f"{(bytes_ / (1024 * 1024)):.1f} MB"
    return f"{gb:.2f} GB"