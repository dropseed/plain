import debugpy


def attach(endpoint=("localhost", 5678)):
    if debugpy.is_client_connected():
        print("Debugger already attached")
        return

    debugpy.listen(endpoint)
    print("Waiting for debugger to attach...")
    debugpy.wait_for_client()
    print("Debugger attached!")
