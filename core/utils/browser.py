import os
import platform


def should_attempt_browser_launch() -> bool:
    """
    Determines if we should attempt to launch a browser for authentication
    based on the user's environment.

    This is an adaptation of the logic from the Google Cloud SDK.
    @returns True if the tool should attempt to launch a browser.
    """
    # A list of browser names that indicate we should not attempt to open a
    # web browser for the user.
    browser_blocklist = ['www-browser']
    browser_env = os.environ.get('BROWSER')
    if browser_env and browser_env in browser_blocklist:
        return False
    
    # Common environment variables used in CI/CD or other non-interactive shells.
    if os.environ.get('CI') or os.environ.get('DEBIAN_FRONTEND') == 'noninteractive':
        return False

    # The presence of SSH_CONNECTION indicates a remote session.
    # We should not attempt to launch a browser unless a display is explicitly available
    # (checked below for Linux).
    is_ssh = bool(os.environ.get('SSH_CONNECTION'))

    # On Linux, the presence of a display server is a strong indicator of a GUI.
    if platform.system() == 'Linux':
        # These are environment variables that can indicate a running compositor on
        # Linux.
        display_variables = ['DISPLAY', 'WAYLAND_DISPLAY', 'MIR_SOCKET']
        has_display = any(os.environ.get(v) for v in display_variables)
        if not has_display:
            return False
    
    # If in an SSH session on a non-Linux OS (e.g., macOS), don't launch browser.
    # The Linux case is handled above (it's allowed if DISPLAY is set).
    if is_ssh and platform.system() != 'Linux':
        return False

    # For non-Linux OSes, we generally assume a GUI is available
    # unless other signals (like SSH) suggest otherwise.
    # The `open` command's error handling will catch final edge cases.
    return True