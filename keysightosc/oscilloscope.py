import visa as vi


def list_connected_devices():
    """List all connected VISA device addresses."""
    rm = vi.ResourceManager()
    resources = rm.list_resources()
    return resources
